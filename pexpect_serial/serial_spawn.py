'''This is like pexpect, but it will work with serial port that you
pass it. You are reponsible for opening and close the serial port.
This allows you to use Pexpect with Serial port which pyserial supports.

PEXPECT LICENSE

    This license is approved by the OSI and FSF as GPL-compatible.
        https://opensource.org/licenses/ISC

    Copyright (c) 2012, Noah Spurrier <noah@noah.org>
    PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
    PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
    COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
    THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
    WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
    MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
    ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
    ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
    OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

'''

"""
Provides an interface like pexpect.spawn interface using pyserial.
Reference to the implementation of popen_spawn.py
"""
import os
import threading
import subprocess
import sys
import time


try:
    from queue import Queue, Empty  # Python 3
except ImportError:
    from Queue import Queue, Empty  # Python 2


from pexpect.spawnbase import SpawnBase, PY3
from pexpect.exceptions import TIMEOUT, EOF, ExceptionPexpect
from pexpect.utils import string_types

__all__ = ['SerialSpawn', 'ExceptionSerialSpawn']

# Exception classes used by this module.


class ExceptionSerialSpawn(ExceptionPexpect):
    '''Raised for serial_spawn exceptions.
    '''

    def __init__(self, value):
        super(ExceptionSerialSpawn, self).__init__(value)


class SerialSpawn(SpawnBase):
    '''This is like pexpect.spawn but allows you to supply a serial created by
    pyserial.'''
    if PY3:
        crlf = '\n'.encode('ascii')
    else:
        crlf = '\n'

    def __init__(self, ser, args=None, timeout=30, maxread=2000, searchwindowsize=None,
                 logfile=None, encoding=None, codec_errors='strict'):
        '''This takes a serial of pyserial as input. Please make sure the serial is open
        before creating SerialSpawn.'''
        super(SerialSpawn, self).__init__(timeout, maxread, searchwindowsize, logfile,
                                          encoding=encoding, codec_errors=codec_errors)

        self.ser = ser
        if not ser.isOpen():
            raise ExceptionSerialSpawn('serial port is not ready')

        self.args = None
        self.command = None

        self.own_fd = False
        self.closed = False
        self.name = '<serial port %s>' % ser.port

        self._buf = self.string_type()

        self._read_queue = Queue()
        self._read_thread = threading.Thread(target=self._read_incoming)
        self._read_thread.setDaemon(True)
        self._read_thread.start()

        # used to match the command-line prompt
        self.UNIQUE_PROMPT = r"\[PEXPECT\][\$\#] "
        self.PROMPT = self.UNIQUE_PROMPT
        # used to set shell command-line prompt to UNIQUE_PROMPT.
        self.PROMPT_SET_SH = r"PS1='[PEXPECT]\$ '"
        self.PROMPT_SET_CSH = r"set prompt='[PEXPECT]\$ '"

    def set_prompt(self, new_prompt):
        self.PROMPT = new_prompt

    def set_linesep(self, sep='\r\n'):
        self.linesep = sep.encode('utf-8')

    def close(self):
        """Close the serial port.

        Calling this method a second time does nothing.
        """
        if not self.ser.isOpen():
            return

        self.flush()
        self.ser.close()
        self.closed = True

    def isalive(self):
        '''This checks if the serial port is still valid.'''
        is_alive = self.ser.isOpen() and self._read_thread.is_alive()
        return is_alive

    _read_reached_eof = False

    def read_nonblocking(self, size, timeout):
        buf = self._buf
        if self._read_reached_eof:
            # We have already finished reading. Use up any buffered data,
            # then raise EOF
            if buf:
                self._buf = buf[size:]
                return buf[:size]
            else:
                self.flag_eof = True
                raise EOF('End Of File (EOF).')

        if timeout == -1:
            timeout = self.timeout
        elif timeout is None:
            timeout = 1e6

        t0 = time.time()
        while (time.time() - t0) < timeout and size and len(buf) < size:
            try:
                incoming = self._read_queue.get_nowait()
            except Empty:
                break
            else:
                if incoming is None:
                    self._read_reached_eof = True
                    break

                buf += self._decoder.decode(incoming, final=False)

        r, self._buf = buf[:size], buf[size:]

        self._log(r, 'read')
        return r

    def _read_incoming(self):
        """Run in a thread to move output from a pipe to a queue."""
        #fileno = self.proc.stdout.fileno()
        while 1:
            buf = b''
            try:
                buf = self.ser.read()  # os.read(fileno, 1024)
            except OSError as e:
                self._log(e, 'read')

            if not buf:
                # This indicates we have reached EOF
                self._read_queue.put(None)
                return

            self._read_queue.put(buf)

    def send(self, s):
        "Write to serial, return number of bytes written"
        s = self._coerce_send_string(s)
        self._log(s, 'send')

        b = self._encoder.encode(s, final=False)
        return self.ser.write(b)

    def sendline(self, s):
        "Write to fd with trailing newline, return number of bytes written"
        s = self._coerce_send_string(s)
        return self.send(s + self.linesep)

    def write(self, s):
        "Write to serial, return None"
        self.send(s)

    def writelines(self, sequence):
        "Call self.write() for each item in sequence"
        for s in sequence:
            self.write(s)

    def prompt(self, timeout=-1):
        '''Match the next shell prompt.
        This is little more than a short-cut to the :meth:`~pexpect.spawn.expect`
        method.
        Calling :meth:`prompt` will erase the contents of the :attr:`before`
        attribute even if no prompt is ever matched. If timeout is not given or
        it is set to -1 then self.timeout is used.

        :return: True if the shell prompt was matched, False if the timeout was
                 reached.
        '''

        if timeout == -1:
            timeout = self.timeout
        patterns = []
        if isinstance(self.PROMPT, list) or isinstance(self.PROMPT, tuple):
            patterns = self.PROMPT
            patterns.append(TIMEOUT)
        elif isinstance(self.PROMPT, str):
            patterns = [self.PROMPT, TIMEOUT]
        else:
            raise ExceptionSerialSpawn("Wrong PROMT:%s" % (str(self.PROMPT)))
        i = self.expect(patterns, timeout=timeout)
        if len(patterns)-1 == i:
            return False
        return True

    def search_last_prompt(self):
        '''
        Sometimes, there are more than one prompt are read at beginning.
        Skip them.This will take a long time as it must reach the timeout.
        '''
        while not self.prompt(1):
            pass

    def set_unique_prompt(self):
        '''This only used when the serial interface is linux terminal.
        This sets the remote prompt to something more unique than ``#`` or ``$``.
        '''
        self.sendline("unset PROMPT_COMMAND")
        self.PROMPT = self.UNIQUE_PROMPT
        self.sendline(self.PROMPT_SET_SH)  # sh-style
        i = self.expect([TIMEOUT, self.PROMPT], timeout=10)
        if i == 0:  # csh-style
            self.sendline(self.PROMPT_SET_CSH)
            i = self.expect([TIMEOUT, self.PROMPT], timeout=10)
            if i == 0:
                return False
        return True
