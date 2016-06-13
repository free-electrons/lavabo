# *Lavabo*

Lavabo is a tool to remotely control boards which are in a
[LAVA](http://www.linaro.org/initiatives/lava/) infrastructure.

Lavabo allows to remove a given board from the control of LAVA. Then it
magically provides access to the board's serial and is able to power cycle the
board as well as to send files to a TFTP server accessible from the board.

## Overview

Lavabo is a two parts software, organized in a client-server fashion. A server
part is running alongside the LAVA instance. The client is provided to control
the boards from remote systems (from LAVA point of view). Last but not least,
Lavabo tries as much as possible to reuse known software.

The server abstracts communication to the LAVA instance, and to other daemons
controlling the boards. It uses directly LAVA to take control of the boards and
parses its configuration to learn which commands to use to power-off, reset or
get the board's serial. For now, Lavabo server only provides access to the
devices controlled by the LAVA master node.

The client connects to the server through SSH and send commands. To get a
serial, a port-forwarding SSH process is spawn and a local telnet instance is
created. To send files, the SFTP protocol is used.

## Requirements

Lavabo server needs a running LAVA instance, configured to access the board's
serials with *ser2net*. The machine hosting Lavabo server should be accessible
via SSH as all communications use this protocol.

Lavabo client needs a few programs to be installed: *telnet*, *ssh* and
*python-paramiko*.

## Configuration

### lavabo-server

A dedicated user (which has an authentication token) should be created in the
LAVA instance. It will be used by the Lavabo server to interact with LAVA.

All communications will go through SSH. Lavabo uses an unique and dedicated UNIX
user on the machine hosting Lavabo server. The multiplexing of users is done
thanks to *SSH commands*. To achieve this, the UNIX user's
*$HOME/.ssh/authorized_keys`* should contain one line per user who wants to use
Lavabo. Example:


```
command="python /path/to/lavabo-server <user0's name> $SSH_ORIGINAL_COMMAND" <user0's public key>
command="python /path/to/lavabo-server <user1's name> $SSH_ORIGINAL_COMMAND" <user1's public key>
command="python /path/to/lavabo-server <user2's name> $SSH_ORIGINAL_COMMAND" <user2's public key>
```

User's name are used in lavabo to authenticate the users, given their SSH key.
They are then used to make sure not more than one user is accessing a board at a
time.

Also, give sufficient permission to the dedicated UNIX user to create
directories in the TFTP directory used by LAVA (as advised when installing LAVA,
it should be `/var/lib/lava/dispatcher/tmp` or look at
`/etc/default/tftpd-hpa`):

```
# chgrp <user> /var/lib/lava/dispatcher/tmp
# chmod g+rwx /var/lib/lava/dispatcher/tmp
```

Complete the lavabo-server.conf with the LAVA user and token previously created.
The  URL of the LAVA server API (it should end with `/RPC2`) should also be
specified.

### lavabo

Copy ```lavabo.conf``` as ```$HOME/.lavabo.conf``` and adapt it with the
appropriate settings.

## F.A.Q

### Why?

We have a LAVA lab with boards we often own in only one copy. We have these
boards included in [KernelCI project](https://kernelci.org/) which sends tests
for different kernels to our LAVA lab in order to know if everything is working
on the boards in our lab.

However, we sometime need to have direct access to the boards when work on the
kernel is in progress. We do not want to put the boards physically outside of
the lab each time we want to work on it. This means we want to be able to
remotely power it on or off, get its serial connection and send files to it.

As we want to work on the board without being interrupted by LAVA, we also have
to virtually put the board outside of our lab.

### What can lavabo do on a board?

`$ lavabo -h` should be enough and is up-to-date.

### What's the typical workflow?

```
$ lavabo list	# get a list of available boards
$ export LAVABO_BOARD=<board>
$ lavabo reserve
```

In a dedicated terminal:
```
$ lavabo serial
```

Then you can power-cycle the board and/or upload your kernel images:
```
$ lavabo upload zImage dtb
$ lavabo reset
```

Finally, it is *IMPORTANT* to put back the board under LAVA's control; otherwise
the board won't be used in the farm and by Kernel CI jobs.
```
$ lavabo release
```

### How are files served to the board?

LAVA uses TFTP to serve files to the board, so all we need is to send files from
our laptop to the TFTP directory of the LAVA instance which can be specified by
`--tftp-dir` in lavabo-server. We use SFTP protocol to perform this task. Thus,
we can access from the board the files we need on LAVA instance TFTP server
under a subdirectory named after the username specified with each SSH key.

### How to enable autocompletion?

- Bash:

Add `eval "$(register-python-argcomplete lavabo)"` to your .bashrc.

- Zsh:

Add to your .zshrc: ``` autoload -U +X compinit && compinit autoload -U +X
bashcompinit && bashcompinit eval "$(register-python-argcomplete lavabo)" ```

Source: http://argcomplete.readthedocs.io/en/latest/#synopsis
