r"""Shows whether the tracking PC's packets reach this PC (the Unreal PC), without Unreal.

Close Unreal first (its Moverse source holds the port). In the project folder, with Unreal's own Python:
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" Tools\udp_listen.py 54321
(the Moverse port; Ctrl+C stops). Every second: packets received, from which address, and the head
position in them (tracking cm, as the hub's X/Y/Z). Packets arrive: the network is fine, look at Unreal
(Live Link source and preset). Nothing arrives: the network (the hub's log says from which of its
addresses it sends; TrackingPC/README.md, "If Unreal does not receive the tracking"). If Windows asks
whether Python may use the network, answering is the owner's or IT's decision; without allowing it this
test can show nothing even when packets arrive.
"""
import json
import socket
import sys
import time

HEAD = "moverserig_Head"


def head_position(frame, parents):
    """Head in tracking cm from a Moverse frame: the root's location plus the bone locations down to the
    head (rig axes X left, Y down, Z forward; NDC_Basic uses tracking = (Z, -X, -Y))."""
    names = [bone["Name"] for bone in parents]
    i = names.index(HEAD)
    x = y = z = 0.0
    while i >= 0:
        dx, dy, dz = frame[i]["Location"]
        x, y, z = x + dx, y + dy, z + dz
        i = parents[i]["Parent"]
    return z, -x, -y


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 54321
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as error:
        sys.exit(f"Port {port} is in use ({error}): close Unreal (or anything else receiving on it) and try again.")
    sock.settimeout(0.2)
    print(f"Listening on port {port} of every network of this PC. Start tracking on the hub. Ctrl+C stops.")
    parents, count, senders, head, last = None, 0, set(), None, time.monotonic()
    while True:
        try:
            data, sender = sock.recvfrom(65536)
            count += 1
            senders.add(sender[0])
            message = json.loads(data)
            for name, items in message.items():
                kind = items[0].get("Type")
                if kind == "CharacterSubject":
                    parents = items[1:]
                elif kind == "CharacterAnimation" and parents:
                    head = head_position(items[1:], parents)
        except socket.timeout:
            pass
        except (ValueError, KeyError, IndexError):
            pass  # not a Moverse packet: counted, not decoded
        except KeyboardInterrupt:
            break
        if time.monotonic() - last >= 1.0:
            last = time.monotonic()
            where = f", head X {head[0]:.1f} Y {head[1]:.1f} Z {head[2]:.1f}" if head else ""
            print(f"{time.strftime('%H:%M:%S')}  {count} packets" + (f" from {', '.join(sorted(senders))}" if senders else "")
                  + where, flush=True)
            count, senders = 0, set()


if __name__ == "__main__":
    main()
