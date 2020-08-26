"""
    DockerBridge daemon for knowrob/webrob

    This daemon provides control over user containers via a JSON-RPC interface on port 5001. This must run as
    privileged/root user to access docker.sock - DO NOT DO ANYTHING OTHER THAN DOCKER COMMUNICATION
    Always sanitize method parameters in methods with @pyjsonrpc.rpcmethod annotation where necessary, as they contain
    user input.
"""
import base64
import signal
import sys
import StringIO

import pyjsonrpc

from dockermanager import DockerManager
from filemanager import FileManager, absolute_userpath, data_container_name, lft_transferpath
from securitycheck import *
from timeoutmanager import TimeoutManager
from utils import sysout


def to_deb64_stream(data):
    return StringIO.StringIO(base64.b64decode(data))

class DockerBridge(pyjsonrpc.HttpRequestHandler):

    @pyjsonrpc.rpcmethod
    def start_user_container(self, user_name, neem_group, neem_name, neem_version='latest', knowrob_image='knowrob', knowrob_version='latest'):
        check_containername(user_name, 'container_name')
        # check_containername(neem_group, 'container_name')
        check_containername(neem_name, 'container_name')
        check_containername(knowrob_image, 'container_name')
        #check_containername(neem_version, 'container_name')
        #check_containername(knowrob_version, 'container_name')
        dockermanager.start_user_container(user_name, neem_group, neem_name, neem_version, knowrob_image, knowrob_version)
        timeout.setTimeout(user_name, 600)

    @pyjsonrpc.rpcmethod
    def create_user_data_container(self, user_name):
        check_containername(user_name, 'container_name')
        dockermanager.create_user_data_container(user_name)

    @pyjsonrpc.rpcmethod
    def stop_user_container(self, user_name):
        check_containername(user_name, 'user_container_name')
        dockermanager.stop_user_container(user_name)
        timeout.remove(user_name)

    @pyjsonrpc.rpcmethod
    def container_started(self, user_name):
        check_containername(user_name, 'user_container_name')
        return dockermanager.container_started(user_name)

    @pyjsonrpc.rpcmethod
    def get_container_ip(self, user_name):
        check_containername(user_name, 'user_container_name')
        return dockermanager.get_container_ip(user_name)

    @pyjsonrpc.rpcmethod
    def refresh(self, user_name):
        check_containername(user_name, 'user_container_name')
        timeout.resetTimeout(user_name, 600)

    @pyjsonrpc.rpcmethod
    def files_fromcontainer(self, user_name, sourcefile):
        check_containername(user_name, 'user_container_name')
        check_pathname(sourcefile, 'sourcefile')

        container = data_container_name(user_name)
        file = absolute_userpath(sourcefile)
        data = StringIO.StringIO()
        filemanager.fromcontainer(container, file, data)
        return base64.b64encode(data.getvalue())

    @pyjsonrpc.rpcmethod
    def files_tocontainer(self, user_name, data, targetfile):
        check_containername(user_name, 'user_container_name')
        check_pathname(targetfile, 'targetfile')

        container = data_container_name(user_name)
        file = absolute_userpath(targetfile)
        filemanager.tocontainer(container, to_deb64_stream(data), file, 1000)

    @pyjsonrpc.rpcmethod
    def files_lft_set_writeable(self):
        filemanager.chown_lft(1000, 1000)

    @pyjsonrpc.rpcmethod
    def files_largefromcontainer(self, user_name, sourcefile, targetfile):
        check_pathname(sourcefile, 'sourcefile')
        check_pathname(targetfile, 'targetfile')

        file = absolute_userpath(sourcefile)
        target = lft_transferpath(targetfile)
        self.__largecopy(user_name, file, target)

    @pyjsonrpc.rpcmethod
    def files_largetocontainer(self, user_name, sourcefile, targetfile):
        check_pathname(sourcefile, 'sourcefile')
        check_pathname(targetfile, 'targetfile')

        file = lft_transferpath(sourcefile)
        target = absolute_userpath(targetfile)
        self.__largecopy(user_name, file, target)

    def __largecopy(self, user_name, src, tgt):
        check_containername(user_name, 'user_container_name')

        container = data_container_name(user_name)
        filemanager.copy_with_lft(container, src, tgt, 1000)

    @pyjsonrpc.rpcmethod
    def files_readsecret(self, user_name):
        check_containername(user_name, 'user_container_name')

        container = data_container_name(user_name)
        data = StringIO.StringIO()
        filemanager.fromcontainer(container, '/etc/rosauth/secret', data)
        return data.getvalue()

    @pyjsonrpc.rpcmethod
    def files_writesecret(self, user_name, secret):
        check_containername(user_name, 'user_container_name')

        container = data_container_name(user_name)
        data = StringIO.StringIO(secret)
        filemanager.tocontainer(container, data, '/etc/rosauth/secret')

    @pyjsonrpc.rpcmethod
    def files_exists(self, user_name, file):
        check_containername(user_name, 'user_container_name')
        check_pathname(file, 'file')

        container = data_container_name(user_name)
        checkexisting = absolute_userpath(file)
        return filemanager.exists(container, checkexisting)

    @pyjsonrpc.rpcmethod
    def files_mkdir(self, user_name, dir):
        check_containername(user_name, 'user_container_name')
        check_pathname(dir, 'dir')

        container = data_container_name(user_name)
        file = absolute_userpath(dir)
        filemanager.mkdir(container, file, True, 1000)

    @pyjsonrpc.rpcmethod
    def files_rm(self, user_name, file, recursive=False):
        check_containername(user_name, 'user_container_name')
        check_pathname(file, 'file')

        container = data_container_name(user_name)
        filetorm = absolute_userpath(file)
        filemanager.rm(container, filetorm, recursive)

    @pyjsonrpc.rpcmethod
    def files_ls(self, user_name, dir, recursive=False):
        check_containername(user_name, 'user_container_name')
        check_pathname(dir, 'dir')

        container = data_container_name(user_name)
        file = absolute_userpath(dir)
        return filemanager.listfiles(container, file, recursive)


def handler(signum, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGINT, handler)

dockermanager = DockerManager()
filemanager = FileManager()

sysout("Starting watchdog")
timeout = TimeoutManager(5, dockermanager.stop_user_container)
timeout.start()

http_server = pyjsonrpc.ThreadingHttpServer(
    server_address=('0.0.0.0', 5001),
    RequestHandlerClass=DockerBridge
)

sysout("Starting JSONRPC")
http_server.serve_forever()
