"""Lists the OAK cameras this PC can reach and shows one colour picture of each (README.md, step 3).

Read only: writes no files and changes nothing on the cameras. Each camera is opened one after the
other with a temporary pipeline in its memory, as every DepthAI program does, and closed again;
nothing is flashed or saved on it. Cameras in use by another program (Moverse) cannot be opened.

Run:  python find_cameras.py                    search the network
      python find_cameras.py <address> ...      open these cameras directly (if the search finds none)
"""
import sys

import cv2
import depthai as dai
import numpy as np


def snapshot(info):
    with dai.Pipeline(dai.Device(info)) as pipeline:
        product = pipeline.getDefaultDevice().getProductName()
        cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        queue = cam.requestOutput((640, 400), dai.ImgFrame.Type.BGR888i, fps=10).createOutputQueue()
        pipeline.start()
        for _ in range(20):  # about 2 s, so the auto exposure settles
            frame = queue.get()
        return product, frame.getCvFrame()


def main():
    if sys.argv[1:]:
        devices = [dai.DeviceInfo(address) for address in sys.argv[1:]]
    else:
        print("Searching for cameras...")
        devices = dai.Device.getAllConnectedDevices()
    print(f"{len(devices)} camera(s):")
    for number, info in enumerate(devices, 1):
        print(f"  {number}: ID {info.deviceId or '-'}  address {info.name}  state {info.state.name}")
    if not devices:
        print("None found. Is Moverse closed? If you know the camera addresses, give them: 3_find_cameras.bat <address> ...")
        return

    tiles = []
    for number, info in enumerate(devices, 1):
        print(f"Camera {number} ({info.deviceId or info.name}): ", end="", flush=True)
        try:
            product, image = snapshot(info)
        except Exception as error:  # in use, unreachable or not an OAK: report and go on with the next one
            print(f"could not open it: {error}")
            continue
        print(f"{product}, picture taken")
        tile = cv2.resize(image, (480, 300))
        cv2.rectangle(tile, (0, 0), (480, 28), (0, 0, 0), -1)
        cv2.putText(tile, f"{number}: {info.deviceId or '-'}  {info.name}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        tiles.append(tile)
    if not tiles:
        return

    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
    print("Note the ID of the camera on top of the wall (the one looking at the visitors), then press a key in the picture window.")
    cv2.imshow("OAK cameras (press any key to close)", grid)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
