"""The one exception type the comms layer raises for the user to read."""


class CommsError(Exception):
    """A command failed: no ack, refused, out of range, not connected... str() is the message to show."""
