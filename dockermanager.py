"""
The DockerManager handles all communication with docker api and provides an API for all actions webrob need to perform
with the docker host.
"""
import os
import traceback

import docker
from docker.errors import *
from filemanager import data_container_name, absolute_userpath

from utils import sysout


class DockerManager(object):
    webapp_images = None
    application_images = None

    def __init__(self):
        self.__client = docker.Client(base_url='unix://var/run/docker.sock', version='1.18', timeout=60)

    def start_user_container(self, application_image, user_container_name, ros_distribution, limit_resources=True):
        try:
            all_containers = self.__client.containers(all=True)
            # Stop user container if running
            self.__stop_container__(user_container_name, all_containers)

            user_home_dir = absolute_userpath('')

            sysout("Creating user container " + user_container_name)
            env = {"VIRTUAL_HOST": user_container_name,
                   "VIRTUAL_PORT": '9090',
                   "MONGO_PORT_27017_TCP_ADDR": 'mongo',
                   "MONGO_PORT_27017_TCP_PORT": '27017',
                   "ROS_PACKAGE_PATH": ":".join([
                       "/home/ros/src",
                       "/opt/ros/"+ros_distribution+"/share",
                       "/opt/ros/"+ros_distribution+"/stacks",
                       user_home_dir
            ])}
            links=[]
            if limit_resources:
                mem_limit = 256 * 1024 * 1024

                # default is 1024, meaning that 4 of these containers will receive the same cpu time as one default
                # container. decrease this further if you want to increase the maximum amount of users on the host.
                cpu_shares = 256
            else:
                mem_limit = 0
                cpu_shares = 1024  # Default value

            # link to mongo container
            # TODO: at the moment the mongo container uses network mode *bridge*,
            #       use container specific network instead. but seems we need to switch
            #       to more recent version of dockerpy before.
            env['MONGO_PORT_27017_TCP_ADDR'] = 'mongo'
            env['MONGO_PORT_27017_TCP_PORT'] = '27017'
            links.append(('mongo','mongo'))

            # FIXME read host path from env
            volumes= ['/episodes']
            volume_bindings={
                '/episodes': {'bind': '/episodes', 'mode': 'ro'}
            }
            host_config = self.__client.create_host_config(
                binds=volume_bindings
            )
            self.__client.create_container(application_image, detach=True, tty=True, environment=env,
                                           name=user_container_name, mem_limit=mem_limit, cpu_shares=cpu_shares,
                                           memswap_limit=mem_limit*4,
                                           volumes=volumes, host_config=host_config,
                                           entrypoint=['/opt/ros/'+ros_distribution+'/bin/roslaunch', 'knowrob_roslog_launch', 'knowrob_ease.launch'])
            
            # Read links and volumes from webapp_container ENV
            inspect = self.__client.inspect_image(application_image)
            env = dict(map(lambda x: x.split("="), inspect['Config']['Env']))
            volumes_from = [data_container_name(user_container_name)]

            sysout("Starting user container " + user_container_name)
            self.__client.start(user_container_name,
                                port_bindings={9090: ('127.0.0.1',)},
                                links=links,
                                volumes_from=volumes_from)
        except Exception, e:
            sysout("Error in start_user_container: " + str(e.message))
            traceback.print_exc()

    def create_user_data_container(self, container_name):
        try:
            all_containers = self.__client.containers(all=True)
            user_data_container = data_container_name(container_name)
            if self.__get_container(user_data_container, all_containers) is None:
                sysout("Creating "+user_data_container+" container.")
                self.__client.create_container('knowrob/user_data', detach=True, tty=True, name=user_data_container,
                                               volumes=['/etc/rosauth'], entrypoint='true')
                self.__client.start(user_data_container)
                return True
        except (APIError, DockerException), e:
            sysout("Error in create_user_data_container: " + str(e.message))
            traceback.print_exc()
        return False

    def stop_container(self, container_name):
        try:
            self.__stop_container__(container_name, self.__client.containers(all=True))
        except (APIError, DockerException), e:
            sysout("Error in stop_container: " + str(e.message))

    def __stop_container__(self, container_name, all_containers):
        # check if containers exist:
        if self.__get_container(container_name, all_containers) is not None:
            sysout("Stopping container " + container_name + "...")
            self.__client.stop(container_name, timeout=5)

            sysout("Removing container " + container_name + "...")
            self.__client.remove_container(container_name)

    def get_container_ip(self, container_name):
        try:
            inspect = self.__client.inspect_container(container_name)
            return inspect['NetworkSettings']['IPAddress']
        except (APIError, DockerException), e:
            sysout("Error in get_container_ip: " + str(e.message) + "\n")
            return 'error'
    
    def get_named_images(self, all_images):
        named_images = []
        for img in all_images:
            tags = img['RepoTags']
            if len(tags)==0: continue
            tag0 = tags[0]
            if tag0 == '<none>:<none>': continue
            named_images.append(tag0.split(':')[0])
        return named_images

    def get_container_env(self, container_name, key):
        try:
            inspect = self.__client.inspect_container(container_name)
            env_list = inspect['Config']['Env']
            # Map to list of key-value pairs and convert to dict
            env = dict(map(lambda x: x.split("="), env_list))
            return env[key]
        except Exception, e:
            sysout("Error in get_container_env: " + str(e.message) + "\n")
            return 'error'
    
    def get_container_log(self, container_name):
        try:
            logger = self.__client.logs(container_name, stdout=True, stderr=True, stream=False, timestamps=False)
            logstr = ""
            # TODO: limit number of lines!
            # It seems for a long living container the log gets to huge.
            for line in logger:
                logstr += line
            return logstr
        except (APIError, DockerException), e:
            sysout("Error in get_container_log: " + str(e.message))
            return 'error'

    def container_started(self, container_name, base_image_name=None):
        try:
            cont = self.__get_container(container_name, self.__client.containers())
            if base_image_name is None or cont is None:
                return cont is not None
            
            inspect = self.__client.inspect_container(container_name)
            image = inspect['Config']['Image']
            
            return image == base_image_name
        
        except (APIError, DockerException), e:
            sysout("Error in container_exists: " + str(e.message))
            return False

    @staticmethod
    def __get_container(container_name, all_containers):
        for cont in all_containers:
            if cont['Names'] != None and "/" + container_name in cont['Names']:
                return cont
        return None
