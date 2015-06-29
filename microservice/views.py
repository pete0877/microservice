from pyramid.view import view_config
from example import MathService

@view_config(route_name='test_math_service', renderer='json')
def test_math_service_view(request):
    """Micro service test routine. Calls the local instance of the math server
    without knowing if the request will be proxies to some remote server or not"""
    service = MathService.Instance()
    result = service.add_numbers(2, 3)
    return str(result)
