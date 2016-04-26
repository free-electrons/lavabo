#! /usr/bin/python2

import xmlrpclib
import os
import time
from ConfigParser import ConfigParser
import argparse
import json
import subprocess
import sqlite3
import select
import paramiko
import sys
import fcntl
import urlparse
import ssl
import StringIO

parser = argparse.ArgumentParser(description="Server to allow remote controlling of boards in LAVA.")
parser.add_argument("LAVABO_USER", help="user to authenticate against in lavabo")
parser.add_argument("LAVA_USER", help="username for the LAVA server")
parser.add_argument("LAVA_TOKEN", help="token for LAVA server API")
parser.add_argument("LAVA_SERVER", help="URL of LAVA server API")

subparsers = parser.add_subparsers(dest='cmd', help="subcommands help")
parser_sftp = subparsers.add_parser("internal-sftp", description="Launch sftp server.", help="launch sftp-server.")
parser_sftp.add_argument('--tftp-dir', default="/var/lib/lava/dispatcher/tmp/", help="the TFTP root directory used to serve files to boards.")

parser_port_redirection = subparsers.add_parser("port-redirection", description="Wait infinitely. This is used when needing port redirection for serial connection.", help="wait infinitely. This is used when needing port redirection for serial connection.")

parser_interact = subparsers.add_parser("interact", description="Listen to stdin and answer to stdout.", help="listen to stdin and answer to stdout.")

parser_interact.add_argument('--devices-conf-dir', default="/etc/lava-dispatcher/devices/", help="the directory used to store LAVA device configuration files.")

class Device(object):

    def __init__(self, name, on_command, off_command, serial_command):
        self.name = name
        self.on_command = on_command
        self.off_command = off_command
        self.serial_command = serial_command

    def put_offline(self, user):
        return proxy.scheduler.put_into_maintenance_mode(self.name, "Put offline by %s" % user)

    def put_online(self, user):
        return proxy.scheduler.put_into_online_mode(self.name, "Put online by %s" % user)

    def get_status(self):
        return proxy.scheduler.get_device_status(self.name)

    def power_on(self):
        return subprocess.call(self.on_command.split(), stdout=open(os.devnull, 'wb'))

    def power_off(self):
        return subprocess.call(self.off_command.split(), stdout=open(os.devnull, 'wb'))

    def get_serial_port(self):
        return self.serial_command.split()[2]

def get_device_list():
    devices.clear()
    config_parser = ConfigParser()

    for conf_file in os.listdir(args.devices_conf_dir):
        conf = StringIO.StringIO()
        conf.write('[__main__]\n')
        conf.write(open(os.path.join(args.devices_conf_dir, conf_file)).read())
        conf.seek(0)
        config_parser.readfp(conf)
        device_name = config_parser.get("__main__", "hostname")
        on_command = config_parser.get("__main__", "hard_reset_command")
        off_command = config_parser.get("__main__", "power_off_cmd")
        serial_command = config_parser.get("__main__", "connection_command")
        devices[device_name] = Device(device_name, on_command, off_command, serial_command)
    return devices

def exists(device_name):
    return device_name in devices

def list_devices():
    return sorted(devices.keys())

def create_answer(status, content):
    answer = {}
    answer["status"] = status
    answer["content"] = content
    return json.dumps(answer)

def get_status(device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    return create_answer("success", proxy.scheduler.get_device_status(device_name))

def get_serial(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] != "offline" or device["offline_by"] != args.LAVA_USER:
        return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
    db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
    #FIXME: Fetchone possibly returns None
    reservation = db_cursor.fetchone()
    last_use, made_by, reserved = reservation
    if reserved == 0:
        return create_answer("error", "You have to reserve the device.")
    if made_by != user:
        return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
    return create_answer("success", {"port": int(devices[device_name].get_serial_port())})

def power_on(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] != "offline" or device["offline_by"] != args.LAVA_USER:
        return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
    db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
    #FIXME: Fetchone possibly returns None
    reservation = db_cursor.fetchone()
    last_use, made_by, reserved = reservation
    if reserved == 0:
        return create_answer("error", "You have to reserve the device.")
    if made_by != user:
        return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
    if devices[device_name].power_on() == 0:
        return create_answer("success", "Device successfully powered on.")
    return create_answer("error", "Failed to power on device.")

def power_off(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] != "offline" or device["offline_by"] != args.LAVA_USER:
        return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
    db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
    #FIXME: Fetchone possibly returns None
    reservation = db_cursor.fetchone()
    last_use, made_by, reserved = reservation
    if reserved == 0:
        return create_answer("error", "You have to reserve the device.")
    if made_by != user:
        return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
    if devices[device_name].power_off() == 0:
        return create_answer("success", "Device successfully powered off.")
    return create_answer("error", "Failed to power off device.")

def put_offline(db_cursor, user, device_name, thief=False, cancel_job=False, force=False):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] == "idle":
        if devices[device_name].put_offline(user):
            return create_answer("error", "Failed to put device offline.")
        db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 1))
        db_cursor.connection.commit()
        return create_answer("success", "Device put offline.")
    if device["status"] == "offline":
        if device["offline_by"] != args.LAVA_USER:
            return create_answer("error", "Device has been reserved in LAVA without this tool.")
        db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
        #FIXME: Fetchone possibly returns None
        reservation = db_cursor.fetchone()
        last_use, made_by, reserved = reservation
        if reserved == 1:
            if made_by != user:
                return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
            return create_answer("success", "You have already put this device offline.")
        db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 1))
        db_cursor.connection.commit()
        return create_answer("success", "Device put offline.")
    #FIXME: What about reserved, offlining, running?
    return create_answer("error", "Device is probably running a job.")

def put_online(db_cursor, user, device_name, force=False):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] == "idle":
        return create_answer("success", "Device is already online.")
    if device["status"] == "offline":
        if device["offline_by"] != args.LAVA_USER:
            return create_answer("error", "Device has been reserved in LAVA without this tool.")
        db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
        #FIXME: Fetchone possibly returns None
        reservation = db_cursor.fetchone()
        last_use, made_by, reserved = reservation
        if made_by == user:
            if devices[device_name].put_online(user):
                return create_answer("error", "Failed to put device online.")
            db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 0))
            db_cursor.connection.commit()
            return create_answer("success", "Device put online.")
        return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
    #FIXME: What about reserved, offlining, running?
    return create_answer("error", "Device is probably running a job.")

def handle(data, stdout):
    data = json.loads(data)
    user = args.LAVABO_USER
    db_conn = sqlite3.connect("remote-control.db")
    db_cursor = db_conn.cursor()
    try:
        db_cursor.execute('SELECT * FROM users WHERE username = ?', (user,))
        db_user = db_cursor.fetchone()
        if not db_user:
            os.write(stdout, create_answer("error", "User does not exist.")+"\n")
            return
        ans = create_answer("error", "Missing board name.")
        if "list" in data:
            ans = create_answer("success", list_devices())
        elif "tftp" in data:
            ans = create_answer("success", str(os.path.join(args.tftp_dir, user)))
        elif "update" in data:
            get_device_list()
            ans = create_answer("success", "Devices list updated.")
        #This is status from LAVA, offline_by will always be "daemon"
        #TODO: Add a status_remote to display the user who is working on the board
        elif "status" in data:
            status = data["status"]
            if "board" in status:
                ans = get_status(status["board"])
        elif "serial" in data:
            if "board" in data["serial"]:
                ans = get_serial(db_cursor, user, data["serial"]["board"])
        elif "online" in data:
            if "board" in data["online"]:
                ans = put_online(db_cursor, user, data["online"]["board"], data["online"].get("force", False))
        elif "offline" in data:
            if "board" in data["offline"]:
                ans = put_offline(db_cursor, user, data["offline"]["board"], data["offline"].get("thief", False), data["offline"].get("cancel_job", False))
        elif "power-on" in data:
            if "board" in data["power-on"]:
                ans = power_on(db_cursor, user, data["power-on"]["board"])
        elif "power-off" in data:
            if "board" in data["power-off"]:
                ans = power_off(db_cursor, user, data["power-off"]["board"])
        else:
            ans = create_answer("error", "Unknown command.")
        os.write(stdout, ans+"\n")
    finally:
        db_cursor.close()
        db_conn.close()

# Taken from https://github.com/jborg/attic/blob/master/attic/remote.py
BUFSIZE = 10 * 1024 * 1024

def serve():
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    # Make stdin non-blocking
    fl = fcntl.fcntl(stdin_fd, fcntl.F_GETFL)
    fcntl.fcntl(stdin_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    # Make stdout blocking
    fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
    fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    while True:
       r, w, es = select.select([stdin_fd], [], [], 10)
       if r:
           data = os.read(stdin_fd, BUFSIZE)
           if not data:
               return
           handle(data, stdout_fd)

# Taken from: https://github.com/kernelci/lava-ci/blob/master/lib/utils.py
def validate_input(username, token, server):
    url = urlparse.urlparse(server)
    if url.path.find('RPC2') == -1:
        print "LAVA Server URL must end with /RPC2"
        sys.exit(1)
    return url.scheme + '://' + username + ':' + token + '@' + url.netloc + url.path

def connect(url):
    try:
        if 'https' in url:
            context = hasattr(ssl, '_create_unverified_context') and ssl._create_unverified_context() or None
            connection = xmlrpclib.ServerProxy(url, transport=xmlrpclib.SafeTransport(use_datetime=True, context=context))
        else:
            connection = xmlrpclib.ServerProxy(url)
        return connection
    except (xmlrpclib.ProtocolError, xmlrpclib.Fault, IOError) as e:
        print "Unable to connect to %s" % url
        sys.exit(1)

def init_db():
    db_conn = sqlite3.connect("remote-control.db")
    db_cursor = db_conn.cursor()
    db_cursor.execute("CREATE TABLE IF NOT EXISTS users (username PRIMARY KEY)")
    db_cursor.execute("CREATE TABLE IF NOT EXISTS devices (hostname PRIMARY KEY)")
    db_conn.execute("CREATE TABLE IF NOT EXISTS reservations (device_name, last_use INTEGER, made_by, reserved INTEGER, FOREIGN KEY(device_name) REFERENCES devices(hostname), FOREIGN KEY(made_by) REFERENCES users(username))")
    db_cursor.execute("INSERT OR IGNORE INTO users VALUES ('0leil')")
    db_cursor.execute("INSERT OR IGNORE INTO users VALUES ('0leil1')")
    db_cursor.execute("INSERT OR IGNORE INTO devices VALUES ('sun8i-a33-sinlinx-sina33_01')")
    db_cursor.execute("INSERT OR IGNORE INTO reservations VALUES ('sun8i-a33-sinlinx-sina33_01', 0, NULL, 0)")
    db_conn.commit()
    db_cursor.close()
    db_conn.close()

args = parser.parse_args()
devices = {}
proxy = None

init_db()
url = validate_input(args.LAVA_USER, args.LAVA_TOKEN, args.LAVA_SERVER)
proxy = connect(url)

if args.cmd == "internal-sftp":
    subprocess.call(("/usr/lib/openssh/sftp-server -d %s" % os.path.join(args.tftp_dir, args.LAVABO_USER)).split())
elif args.cmd == "port-redirection":
    while True:
        time.sleep(1000)
else:
    get_device_list()
    serve()
