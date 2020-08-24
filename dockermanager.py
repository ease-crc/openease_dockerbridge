"""
The DockerManager handles all communication with docker api and provides an API for all actions webrob need to perform
with the docker host.
"""
import os
import traceback

import docker
from docker.errors import *
from filemanager import data_container_name, knowrob_container_name, mongo_container_name, user_network_name, absolute_userpath

from utils import sysout

USER_DATA_IMAGE='knowrob/user_data'
# TODO: make configurable
KNOWROB_IMAGE_PREFIX='openease'
NEEM_DIR=os.environ['NEEM_DIR']

class DockerManager(object):
    def __init__(self):
        self.__client = docker.Client(base_url='unix://var/run/docker.sock',
                                      version='1.22',
                                      timeout=60)
        self.__client.pull(USER_DATA_IMAGE)
    
    def start_user_container(self, user_name,
                             neem_group, neem_name, neem_version,
                             knowrob_image, knowrob_version):
        try:
            all_containers = self.__client.containers(all=True)
            # Stop user container if running
            self.__stop_user_container__(user_name, all_containers)
            # make sure the image is locally available
            # TODO: manage knowrob images, delete old ones that were not used for a while
            # FIXME: this overwrites any local image with this tag
            #self.__client.pull(KNOWROB_IMAGE_PREFIX+'/'+knowrob_image,
            #                   tag=knowrob_version)
            # Host directory where the NEEM is located.
            # This directory is mounted as volume into the dockerbridge container.
            # neem_dir_local = neem_group+'/'+neem_name #+'/'+neem_version
            # create user container
            self.__create_user_data_container__(user_name,all_containers)
            self.__create_user_network__(user_name)
            self.__create_knowrob_container__(user_name,knowrob_image,knowrob_version)
        except Exception, e:
            sysout("Error in start_user_container: " + str(e.message))
            traceback.print_exc()

    def create_user_data_container(self, user_name):
        try:
            all_containers = self.__client.containers(all=True)
            self.__create_user_data_container__(user_name, all_containers)
            return True
        except (APIError, DockerException), e:
            sysout("Error in create_user_data_container: " + str(e.message))
            traceback.print_exc()
        return False

    def __create_user_network__(self, user_name):
        network_name = user_network_name(user_name)
        if self.__client.networks(names=[network_name]) == []:
            sysout("Creating "+network_name+" network.")
            self.__client.create_network(name=network_name)

    def __create_user_data_container__(self, user_name, all_containers):
        user_data_container = data_container_name(user_name)
        if self.__get_container(user_data_container, all_containers) is None:
            sysout("Creating "+user_data_container+" container.")
            self.__client.create_container('knowrob/user_data',
                                           detach=True,
                                           tty=True,
                                           name=user_data_container,
                                           volumes=['/etc/rosauth'],
                                           entrypoint='true')
            # TODO: start needed for volume? will exit right away, or not?
            self.__client.start(user_data_container)

    def __create_knowrob_container__(self, user_name, knowrob_image, knowrob_version):
        knowrob_container = knowrob_container_name(user_name)
        network_name = user_network_name(user_name)
        user_home_dir = absolute_userpath('')

        sysout("Creating user container " + knowrob_container)
        env = {"VIRTUAL_HOST": knowrob_container,
               "VIRTUAL_PORT": '9090'
        }
        # TODO: make this configurable based on the roles of the user
        limit_resources = True
        if limit_resources:
            mem_limit = 256 * 1024 * 1024
            # default is 1024, meaning that 4 of these containers will receive the same cpu time as one default
            # container. decrease this further if you want to increase the maximum amount of users on the host.
            cpu_shares = 256
        else:
            mem_limit = 0
            cpu_shares = 1024  # Default value
        host_config = self.__client.create_host_config(
            mem_limit=mem_limit, 
            memswap_limit=mem_limit*4,
        )
        # TODO: handle version tag
        self.__client.create_container("openease/knowrob",
                                       detach=True,
                                       tty=True,
                                       environment=env,
                                       name=knowrob_container,
                                       cpu_shares=cpu_shares,
                                       host_config=host_config)
        self.__client.connect_container_to_network(knowrob_container, network_name)
        ##
        sysout("Starting user container " + knowrob_container)
        volumes_from = [data_container_name(user_name)]
        self.__client.start(knowrob_container,
                            port_bindings={9090: ('127.0.0.1',)},
                            volumes_from=volumes_from)

    def stop_user_container(self, user_name):
        try:
            self.__stop_user_container__(user_name, self.__client.containers(all=True))
        except (APIError, DockerException), e:
            sysout("Error in stop_user_container: " + str(e.message))
    
    def __stop_user_container__(self, user_name, all_containers):
        self.__stop_container__(knowrob_container_name(user_name), all_containers)
        self.__stop_container__(mongo_container_name(user_name), all_containers)
        # TODO: destroy user network

    def __stop_container__(self, container_name, all_containers):
        # check if containers exist:
        if self.__get_container(container_name, all_containers) is not None:
            sysout("Stopping container " + container_name + "...")
            self.__client.stop(container_name, timeout=5)
            sysout("Removing container " + container_name + "...")
            self.__client.remove_container(container_name)

    def get_container_ip(self, user_name):
        try:
            inspect = self.__client.inspect_container(knowrob_container_name(user_name))
            return inspect['NetworkSettings']['IPAddress']
        except (APIError, DockerException), e:
            sysout("Error in get_container_ip: " + str(e.message) + "\n")
            return 'error'

    def container_started(self, user_name, base_image_name=None):
        try:
            return self.__get_container(knowrob_container_name(user_name), self.__client.containers()) is not None
        except (APIError, DockerException), e:
            sysout("Error in container_exists: " + str(e.message))
            return False

    @staticmethod
    def __get_container(container_name, all_containers):
        for cont in all_containers:
            if cont['Names'] != None and "/" + container_name in cont['Names']:
                return cont
        return None
