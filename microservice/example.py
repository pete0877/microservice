import logging

from microservice.base import *

logger = logging.getLogger(__name__)

@MicroServiceSingleton
class MathService():
    """Simple math micro service"""

    @MicroServiceMethod
    def add_numbers(self, a=0, b=0):
        logger.info("inside MathService.add_numbers(a=%s, b=%s)" % (a, b))
        return a + b
