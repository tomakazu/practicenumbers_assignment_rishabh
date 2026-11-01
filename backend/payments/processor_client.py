"""The only place where the payments app talks to the payment processor.

It never imports the processor's models or reads its tables. It calls the
processor's public charge function and turns the processor's errors into
our own ProcessorError, so the rest of the payments app never depends on
processor internals.
"""
from mock_processor import services as processor


class ProcessorError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def charge(payment_token, amount, currency):
    try:
        result = processor.charge(payment_token, amount, currency)
    except processor.ChargeError as error:
        raise ProcessorError(error.code, error.message) from error
    return result["processor_reference"]
