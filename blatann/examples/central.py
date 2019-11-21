"""
This example demonstrates implementing a central BLE connection in a procedural manner. Each bluetooth operation
performed is done sequentially in a linear fashion, and the main context blocks until each operation completes
before moving on to the rest of the program

This is designed to work alongside the peripheral example running on a separate nordic chip
"""
import struct
from blatann import BleDevice, uuid
from blatann.gap import smp
from blatann.examples import example_utils, constants
from blatann.nrf import nrf_events

logger = example_utils.setup_logger(level="DEBUG")


def on_counting_char_notification(characteristic, event_args):
    """
    Callback for when a notification is received from the peripheral's counting characteristic.
    The peripheral will periodically notify a monotonically increasing, 4-byte integer. This callback unpacks
    the value and logs it out

    :param characteristic: The characteristic the notification was on (counting characteristic)
    :param event_args: The event arguments
    :type event_args: blatann.event_args.NotificationReceivedEventArgs
    """
    # Unpack as a little-endian, 4-byte integer
    current_count = struct.unpack("<I", event_args.value)[0]
    logger.info("Counting char notification. Curent count: {}".format(current_count))


def main(serial_port):
    # Set the target to the peripheral's advertised name
    target_device_name = constants.PERIPHERAL_NAME

    # Create and open the BLE device (and suppress spammy logs)
    ble_device = BleDevice(serial_port)
    ble_device.event_logger.suppress(nrf_events.GapEvtAdvReport)
    ble_device.open()

    # Set the scanner to scan for 4 seconds
    ble_device.scanner.set_default_scan_params(timeout_seconds=4)

    logger.info("Scanning for '{}'".format(target_device_name))
    target_address = example_utils.find_target_device(ble_device, target_device_name)

    if not target_address:
        logger.info("Did not find target peripheral")
        return

    # Initiate the connection and wait for it to finish
    logger.info("Found match: connecting to address {}".format(target_address))
    peer = ble_device.connect(target_address).wait()
    if not peer:
        logger.warning("Timed out connecting to device")
        return

    # Wait up to 10 seconds for service discovery to complete
    logger.info("Connected, conn_handle: {}".format(peer.conn_handle))
    _, event_args = peer.discover_services().wait(10, exception_on_timeout=False)
    logger.info("Service discovery complete! status: {}".format(event_args.status))

    # Log each service found
    for service in peer.database.services:
        logger.info(service)

    peer.set_connection_parameters(100, 120, 6000)  # Discovery complete, go to a longer connection interval

    # Pair with the peripheral
    def on_passkey_entry(peer, passkey_event_args):
        """
        Callback for when the user is requested to enter a passkey to resume the pairing process.
        Requests the user to enter the passkey and resolves the event with the passkey entered

        :param peer: the peer the passkey is for
        :param passkey_event_args:
        :type passkey_event_args: blatann.event_args.PasskeyEntryEventArgs
        """
        passkey = input("Enter peripheral passkey: ")
        passkey_event_args.resolve(passkey)

    # Setup the security parameters
    peer.security.set_security_params(passcode_pairing=True, io_capabilities=smp.IoCapabilities.KEYBOARD_DISPLAY,
                                      bond=False, out_of_band=False)
    # Register the callback for when a passkey needs to be entered by the user
    peer.security.on_passkey_required.register(on_passkey_entry)
    # Wait up to 60 secomds for the pairing process
    peer.security.pair().wait(60)

    # Find the counting characteristic
    counting_char = peer.database.find_characteristic(constants.COUNTING_CHAR_UUID)
    if counting_char:
        logger.info("Subscribing to the counting characteristic")
        counting_char.subscribe(on_counting_char_notification).wait(5)
    else:
        logger.warning("Failed to find counting characteristic")

    # Find the hex conversion characteristic. This characteristic takes in a bytestream and converts it to its
    # hex representation. e.g. '0123' -> '30313233'
    hex_convert_char = peer.database.find_characteristic(constants.HEX_CONVERT_CHAR_UUID)
    if hex_convert_char:
        # Generate some data ABCDEFG... Then, incrementally send increasing lengths of strings.
        # i.e. first send 'A', then 'AB', then 'ABC'...
        data_to_convert = bytes(ord('A') + i for i in range(12))
        for i in range(len(data_to_convert)):
            data_to_send = data_to_convert[:i+1]
            logger.info("Converting to hex data: '{}'".format(data_to_send))

            # Write the data, waiting up to 5 seconds for the write to complete
            if not hex_convert_char.write(data_to_send).wait(5, False):
                logger.error("Failed to write data, i={}".format(i))
                break

            # Write was successful, when we read the characteristic the peripheral should have converted the string
            # Once again, initiate a read and wait up to 5 seconds for the read to complete
            char, event_args = hex_convert_char.read().wait(5, False)
            logger.info("Hex: '{}'".format(event_args.value.decode("ascii")))
    else:
        logger.warning("Failed to find hex convert char")

    # Clean up
    logger.info("Disconnecting from peripheral")
    peer.disconnect().wait()
    ble_device.close()


if __name__ == '__main__':
    main("COM9")
