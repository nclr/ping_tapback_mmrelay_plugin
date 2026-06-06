import asyncio
import logging
import re
from mmrelay.plugins.base_plugin import BasePlugin
from mmrelay.meshtastic_utils import connect_meshtastic
from meshtastic.protobuf.mesh_pb2 import MeshPacket, ToRadio
from meshtastic.protobuf.portnums_pb2 import PortNum
from meshtastic.util import fromStr as nodeIdFromStr

logging.getLogger('meshtastic').setLevel(logging.INFO)

BROADCAST_NUM = 0xFFFFFFFF

emoji_map = {0: "0️⃣", 1: "1️⃣", 2: "2️⃣", 3: "3️⃣",
             4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣"}

# Matches "ping" or "test" anywhere in the message
# TRIGGER_PATTERN = re.compile(r'(ping|test)', re.IGNORECASE)


TRIGGER_WORDS = [
    "ping",
    "test",
    "hello",
    "π[ίι]νγκ",
    "τ[έε]στ",
]

TRIGGER_PATTERN = re.compile(r'(' + '|'.join(TRIGGER_WORDS) + r')', re.IGNORECASE)



# Matches "καλημέρα" with or without accent on the έ, any case (Greek Unicode)
GREETING_PATTERN = re.compile(r'(καλημ[εέ]ρα|kal[ih]mera)', re.IGNORECASE | re.UNICODE)

class Plugin(BasePlugin):
    plugin_name = "ping_tapback"

    def start(self):
        self.client = connect_meshtastic()
        if not self.client:
            self.logger.error(f"[{self.plugin_name}] Failed to connect on startup")
        else:
            self.logger.info(f"[{self.plugin_name}] Meshtastic client connected")

    async def handle_meshtastic_message(self, packet, formatted_message, longname, meshnet_name):
        my_node = self.get_my_node_id()
        if packet.get("from") == my_node or packet.get("fromId") == my_node:
            return False

        if "decoded" not in packet or "text" not in packet["decoded"]:
            return False

        message = packet["decoded"]["text"].strip().lower()
        
        is_greeting = bool(GREETING_PATTERN.search(message))
        is_trigger  = bool(TRIGGER_PATTERN.search(message))

        if not is_greeting and not is_trigger:
            return False

        hop_start  = packet.get("hopStart")
        hop_limit  = packet.get("hopLimit")
        hops = max(0, min((hop_start or 0) - (hop_limit or 0), 8)) if hop_start is not None else 0

        self.logger.info(f"[{self.plugin_name}] hopStart is {hop_start}, hopLimit is {hop_limit}. So hops are {hops}")
        hops_emoji = emoji_map.get(hops, f"🔢{hops}")

        emoji = "☀️" if is_greeting else hops_emoji

        channel = packet.get("channel", 0)
        is_dm   = self.is_direct_message(packet)

        if not self.is_channel_enabled(channel, is_direct_message=is_dm):
            self.logger.warning(f"[{self.plugin_name}] Channel/DM not enabled")
            return False

        await asyncio.sleep(self.get_response_delay())

        message_id = packet.get("id")
        if not message_id:
            self.logger.error(f"[{self.plugin_name}] No message ID found")
            return False

        if not self.client:
            self.logger.error(f"[{self.plugin_name}] No Meshtastic client available")
            return False

        try:
            from_id = packet.get("from") or packet.get("fromId")
            if isinstance(from_id, str):
                dest_id = nodeIdFromStr(from_id)
            elif isinstance(from_id, int):
                dest_id = from_id
            else:
                dest_id = BROADCAST_NUM

            msh = MeshPacket()
            msh.to               = dest_id if is_dm else BROADCAST_NUM
            msh.channel          = int(channel)
            msh.id               = self.client._generatePacketId()
            msh.hop_limit        = hop_start or 3
            msh.want_ack         = False
            msh.decoded.portnum  = PortNum.TEXT_MESSAGE_APP
            msh.decoded.payload  = emoji.encode("utf-8")
            msh.decoded.emoji    = 1
            msh.decoded.reply_id = int(message_id)

            # TCPInterface requires wrapping MeshPacket inside ToRadio
            to_radio = ToRadio()
            to_radio.packet.CopyFrom(msh)
            self.client._send_to_radio(to_radio)

            self.logger.info(
                f"[{self.plugin_name}] ✅ tapback {emoji} sent to {longname} "
                f"(to={msh.to:#010x} hops={hops})"
            )

        except Exception as e:
            self.logger.error(f"[{self.plugin_name}] Failed to send tapback: {e}", exc_info=True)

        return False

    async def handle_room_message(self, room, event, full_message):
        return False
