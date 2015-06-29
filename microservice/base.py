import os
import socket
import random
import logging
import requests

from ConfigParser import SafeConfigParser
from pyramid.response import Response
from pyramid.httpexceptions import HTTPBadRequest
from pyramid.httpexceptions import HTTPInternalServerError

logger = logging.getLogger(__name__)


class MicroServiceDispatcher(object):
    """Responsible for responding to HTTP calls to all micro services and dispatches
    them to the local service instances"""

    instance_registry = {}

    @classmethod
    def register_service_instance(cls, service_name, service_instance):
        MicroServiceDispatcher.instance_registry[service_name] = service_instance

    def __init__(self, request):
        """Called whenever HTTP requests are made on the base URL path of
        /microservice/{service_class}/{service_method}/
        See dispatch() method for the actual call handler.
        """
        self.request = request
        self.service_class = self.request.matchdict.get('service_class', None)
        self.service_method = self.request.matchdict.get('service_method', None)

    def dispatch(self):
        """Handles the call to service class name stored in self.service_class
        on method name stored in self.service_method"""
        logger.info("Dispatching %s:%s to the local service instance" % (self.service_class, self.service_method))

        service_instance = MicroServiceDispatcher.instance_registry.get(self.service_class, None)
        if not service_instance:
            message = "Micro service '%s' is not registered" % self.service_class
            logger.error(message)
            return HTTPBadRequest(message)


        # DEBUG Hack to force the local service instance to handle the call instead of
        # proxing to another remote server:
        original_proxy_to_remote = service_instance.proxy_to_remote           # remember to revert the hack
        service_instance.proxy_to_remote = False

        # if service_instance.proxy_to_remote:
        # message = "Micro service %s on host %s was called as a remote but it itself is configured to talk to another remote. Returning error to avoid looping forever. Check the hostname configuration. " % (
        # self.service_class, service_instance.hostname)
        # logger.error(message)
        #     return HTTPBadRequest(message)

        # Make sure the service instance supports this method name:
        try:
            method_object = getattr(service_instance, self.service_method)
        except:
            message = "Micro service %s does not have have method named '%s'" % (
                self.service_class, self.service_method)
            logger.error(message)
            return HTTPBadRequest(message)

        # Invoke the local service method:
        try:
            post_json = self.request.json
            args = post_json.get('args', [])
            kwargs = post_json.get('kwargs', {})

            result = method_object(*args, **kwargs)

        except Exception as error:
            message = "Micro service %s.%s(args=%s, kwargs=%s) produced error: %s" % \
                      (self.service_class, self.service_method, args, kwargs, error)
            logger.error(message)
            return HTTPInternalServerError(message)
        finally:
            service_instance.proxy_to_remote = original_proxy_to_remote

        result_response = str(result)
        return Response(result_response, status=200)


class MicroServiceSingleton:
    """Class decorator to force the decorated micro service class to be a singleton.
    Configures the service instance with paremters defined in the .ini file.
    Most importantly, the instance needs to know if it supposed to handle the call
    locally or proxy the call to one of the specified remote servers.

    The decorated class instance should be accessed through the (class).Instance() method.

    The decorated class cannot be inherited from.
    """

    def __init__(self, service_class):
        # Remember the decorated class:
        self._service_class = service_class

    def Instance(self):
        """Returns the singleton instance (by possibly creating it first).
        """
        try:
            return self._service_instance
        except AttributeError:
            self._service_instance = self._service_class()

            # Configure the instance with information about being remote vs local and other params:
            self._configure_instance(self._service_instance, self._service_class)

            # Register the instance with the local HTTP call dispatcher only if the instance is
            # supposed to support the calls locally and not proy to another remote server.
            # if not self._service_instance.proxy_to_remote:
            # MicroServiceDispatcher.register_service_instance(self._service_class.__name__, self._service_instance)

            # .. however, for DEBUG purposes, always register the instance for now:
            MicroServiceDispatcher.register_service_instance(self._service_class.__name__, self._service_instance)

            return self._service_instance


    def _configure_instance(self, service_instance, service_class):
        """Configures the micro service instance with parameters found in the
        .ini config file. Most importantly the instance needs to know if it should
        handle the calls to its method locally or proxy the calls to one of the
        remote servers specified.

        Sample format for the .ini file:

        [MICROSERVICE]
        services=MathService,EchoService

        [MathService]
        servers=localhost:6543,127.0.0.1:6543

        [EchoService]
        servers=pmac3,pmac2
        """
        service_instance.hostname = socket.gethostname()
        service_instance.service_name = service_class.__name__

        # TODO: use the config that's already parsed in app context
        config_file = os.environ.get('ADMGT_SETTINGS', 'development.ini')
        settings = SafeConfigParser()

        if not settings.read(config_file):
            raise IOError("Settings file %s not found" % config_file)

        try:
            all_registered_services = settings.get('MICROSERVICE', 'services').split(',')
            logger.info("All services found in the config file: %s" % all_registered_services)
        except:
            raise Exception("Could not find config section '[MICROSERVICE]' or parameter 'services' in config file %s",
                            config_file)

        if service_instance.service_name not in all_registered_services:
            raise Exception("Service config file %s does not contain service definition for %s" % (
                config_file, service_instance.service_name))

        service_instance.servers = settings.get(service_instance.service_name, 'servers').split(',')
        if not service_instance.servers:
            raise Exception("Service config file %s has no 'servers' variable under the '%s' service section" % (
                config_file, service_instance.service_name))

        # The local hostname must match one of the configured supporting servers exactly in order for it to
        # handle the calls locally. Otherwise we assume the calls to this service will have to be sent
        # via HTTP to one of the remote servers.
        # Since the server specification might be in the form: HOSTNAME:PORT, take only the HOSTNAME part:

        server_names = [host_plus_port.split(':')[0] for host_plus_port in service_instance.servers]
        service_instance.proxy_to_remote = service_instance.hostname not in server_names

        if service_instance.proxy_to_remote:
            logger.info("On this host (%s) service %s is configured to proxy calls to one of these remote servers: %s" %
                        (service_instance.hostname, service_instance.service_name, service_instance.servers))
        else:
            logger.info("On this host (%s) service %s is configured to handle local calls" % (service_instance.hostname,
                        service_instance.service_name))

        return None


    def __call__(self):
        raise TypeError('Singletons must be accessed through the Instance() method.')

    def __instancecheck__(self, inst):
        return isinstance(inst, self._service_class)


def MicroServiceMethod(func):
    """Wraps all micro service methods that are meant to be handled either locally or remotely.
    Handles the HTTP POST call to the remote server / instance if necessary.
    Otherwise it just passes the call to the decorated method."""

    def inner(*args, **kwargs):
        service_instance = args[0]
        service_name = service_instance.__class__.__name__
        function_name = func.func_name

        logger.info("Service decorator handling the call on %s:%s(args=%s, kwargs=%s)" %
                    (service_name, function_name, args, kwargs))

        if service_instance.proxy_to_remote:

            # Pick one of the supporting servers at random:
            random_server = random.choice(service_instance.servers)

            # TODO: Update the Auth to use the server-to-server
            url = "http://%s/microservice/%s/%s/?" % (
                random_server, service_name, function_name)

            method_args = list(args)

            # Strip the first argument since that's the self
            method_args = method_args[1:]
            post_json = {'args': method_args, 'kwargs': kwargs}

            logger.info("Calling remote service at %s with post data: %s ... " % (url, post_json))

            response = requests.post(url, json=post_json, headers={'content-type': 'application/json'})
            logger.info("Got following response (status %s) from the remote service: %s" %
                        (response.status_code, response.text))

            if response.status_code == 200:
                return response.text
            else:
                raise Exception(response.text)
        else:
            logger.info("Doing local service instance call")
            return func(*args, **kwargs)

    return inner
