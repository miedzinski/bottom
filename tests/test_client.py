import asyncio
import pytest
from bottom.client import Client


def test_default_event_loop():
    default_loop = asyncio.get_event_loop()
    client = Client(host="host", port="port")
    assert client.loop is default_loop


def test_send_unknown_command(client, protocol, schedule, flush):
    """ Sending an unknown command raises """
    client.connect()
    flush()
    assert client.protocol is protocol
    with pytest.raises(ValueError):
        client.send("Unknown Command")


def test_send_before_connected(client):
    """ Sending before connected raises """
    with pytest.raises(RuntimeError):
        client.send("PONG")


def test_disconnect_before_connected(client):
    """ Disconnecting a client that's not connected is a no-op """
    assert client.protocol is None
    client.disconnect()
    assert client.protocol is None


def test_send_after_disconnected(client, transport, flush):
    """ Sending after disconnect does not invoke writer """
    client.connect()
    flush()
    client.send("PONG")
    client.disconnect()
    with pytest.raises(RuntimeError):
        client.send("QUIT")
    assert transport.written == [b"PONG\r\n"]


def test_old_connection_lost(client, protocol, flush):
    """ An old connection closing is a no-op """
    client.connect()
    flush()
    assert client.protocol is protocol
    old_conn = object()
    client._connection_lost(old_conn)
    assert client.protocol is protocol


def test_multiple_connect(client, protocol, flush):
    """Establishing a second connection should close the first"""
    client.connect()
    flush()
    assert client.protocol is protocol
    client.connect()
    flush()
    # Because of how we've mocked create_connection, the same protocol
    # instance is always returned.  Regardless, we'll still close it as
    # part of cleaning up the 'previous' connection
    assert client.protocol is protocol
    assert protocol.closed


def test_unpack_triggers_client(client, protocol, flush):
    """ protocol pushes messages to the client """
    received = []

    @client.on("PRIVMSG")
    async def receive(nick, user, host, target, message):
        print("success")
        received.extend([nick, user, host, target, message])

    client.connect()
    flush()
    protocol.data_received(
        b":nick!user@host PRIVMSG #target :this is message\n")
    flush()
    assert received == ["nick", "user", "host", "#target", "this is message"]


def test_on_signature(client):
    """ register a handler with full function signature options"""
    client.on("f")(lambda arg, *args, kw_only, kw_default="d", **kwargs: None)


def test_on_coroutine(client):
    async def handle(arg, *args, kw_only, kw_default="d", **kwargs):
        pass
    client.on("f")(handle)


def test_trigger_no_handlers(client, flush):
    """ trigger an event with no handlers """
    client.trigger("some event")
    flush()


def test_trigger_one_handler(client, watch, flush):
    client.on("f")(lambda: watch.call())
    client.trigger("f")
    flush()
    assert client.triggers["F"] == 1
    assert watch.called


def test_trigger_multiple_handlers(client, flush):
    h1, h2 = 0, 0

    def incr(first=True):
        nonlocal h1, h2
        if first:
            h1 += 1
        else:
            h2 += 1

    client.on("f")(lambda: incr(first=True))
    client.on("f")(lambda: incr(first=False))
    client.trigger("f")
    flush()
    assert h1 == 1
    assert h2 == 1


def test_trigger_unpacking(client, flush):
    """ Usual semantics for unpacking **kwargs """
    called = False

    def func(arg, *args, kw_only, kw_default="default", **kwargs):
        assert arg == "arg"
        assert not args
        assert kw_only == "kw_only"
        assert kw_default == "default"
        assert kwargs["extra"] == "extra"
        nonlocal called
        called = True

    client.on("f")(func)
    client.trigger("f", **{s: s for s in ["arg", "kw_only", "extra"]})
    flush()
    assert called


def test_bound_method_of_instance(client, flush):
    """ verify bound methods are correctly inspected """
    class Class(object):
        def method(self, arg, kw_default="default"):
            assert arg == "arg"
            assert kw_default == "default"

    instance = Class()
    client.on("f")(instance.method)
    client.trigger("f", **{"arg": "arg"})
    flush()


def test_callback_ordering(client, flush, loop):
    """ Callbacks for a second event don't queue behind the first event """
    second_complete = asyncio.Event(loop=loop)
    call_order = []
    complete_order = []

    async def first():
        call_order.append("first")
        await second_complete.wait()
        complete_order.append("first")

    async def second():
        call_order.append("second")
        complete_order.append("second")
        second_complete.set()

    client.on("f")(first)
    client.on("f")(second)

    client.trigger("f")
    flush()
    assert call_order == ["first", "second"]
    assert complete_order == ["second", "first"]
