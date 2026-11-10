"""Errors the posting accounts share."""


class NotReady(RuntimeError):
    """The account can't post right now for a reason found BEFORE any upload started: its sign-in ended, or a key is
    missing. Nothing was sent, so trying again later can't post twice. The clip stays approved and waits."""
