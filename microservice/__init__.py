from pyramid.config import Configurator
from base import MicroServiceDispatcher

def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    config.include('pyramid_chameleon')

    config.add_route('microservice', '/microservice/{service_class}/{service_method}/')
    config.add_view(MicroServiceDispatcher, route_name='microservice', attr='dispatch',
                    request_method='POST', permission='view')

    config.add_route('test_math_service', '/test_math_service')
    config.scan()
    return config.make_wsgi_app()
