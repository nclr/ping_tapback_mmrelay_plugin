import asyncio
import logging
import re
from mmrelay.plugins.base_plugin import BasePlugin
from mmrelay.meshtastic_utils import connect_meshtastic
from meshtastic.protobuf.mesh_pb2 import MeshPacket, ToRadio
from meshtastic.protobuf.portnums_pb2 import PortNum
from meshtastic.util import fromStr as nodeIdFromStr
from meshtastic.mesh_interface_runtime.flows import (
    _node_label, _format_snr, UNKNOWN_SNR_QUARTER_DB,
)
from meshtastic.mesh_interface_runtime.request_wait import WAIT_ATTR_TRACEROUTE
from meshtastic.protobuf import mesh_pb2, portnums_pb2
import google.protobuf.json_format

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

    def get_matrix_commands(self):
        return ["traceroute"]

    async def handle_room_message(self, room, event, full_message):
        full_message = full_message.strip()
        if not full_message.lower().startswith("!traceroute"):
            return False

        parts = full_message.split()
        if len(parts) < 2:
            await self.send_matrix_message(
                room.room_id,
                "Usage: `!traceroute <nodeId>` — e.g. `!traceroute !abcd1234`",
                reply_to_event_id=event.event_id,
            )
            return True

        dest = parts[1]
        if not self.client:
            self.client = connect_meshtastic()
        if not self.client:
            await self.send_matrix_message(
                room.room_id, "❌ No Meshtastic client available.",
                reply_to_event_id=event.event_id,
            )
            return True

        await self.send_matrix_message(
            room.room_id,
            f"🔍 Running traceroute to `{dest}`…",
            reply_to_event_id=event.event_id,
        )

        hop_limit    = 7
        result_lines = []
        result_event = asyncio.Event()
        loop         = asyncio.get_running_loop()

        def node_label(node_num):
            node_id = _node_label(self.client, node_num)  # e.g. "!abcd1234"
            node    = (self.client.nodes or {}).get(node_id, {})
            user    = node.get("user", {})
            long_name  = user.get("longName", "")
            short_name = user.get("shortName", "")
            if long_name and short_name:
                return f"{long_name} ({short_name}) {node_id}"
            return node_id

        def append_hop(s, node_num, snr_val):
            return f"{s} → {node_label(node_num)} ({_format_snr(snr_val)} dB)"

        def on_traceroute_response(p):
            try:
                decoded = p.get("decoded", {})
                payload_bytes = decoded.get("payload")
                if not payload_bytes:
                    return
                rd = mesh_pb2.RouteDiscovery()
                rd.ParseFromString(payload_bytes)
                d = google.protobuf.json_format.MessageToDict(rd)

                route_towards = d.get("route", [])
                snr_towards   = d.get("snrTowards", [])
                snr_valid     = len(snr_towards) == len(route_towards) + 1

                s = node_label(p["to"])
                for i, num in enumerate(route_towards):
                    s = append_hop(s, num, snr_towards[i] if snr_valid else None)
                s = append_hop(s, p["from"], snr_towards[-1] if snr_valid else None)
                result_lines.append(f"**Towards destination:** {s}")

                route_back = d.get("routeBack", [])
                snr_back   = d.get("snrBack", [])
                back_valid = "hopStart" in p and len(snr_back) == len(route_back) + 1
                if back_valid:
                    s = node_label(p["from"])
                    for i, num in enumerate(route_back):
                        s = append_hop(s, num, snr_back[i])
                    s = append_hop(s, p["to"], snr_back[-1] if snr_back else None)
                    result_lines.append(f"**Back to us:** {s}")

                request_id = self.client._extract_request_id_from_packet(p)
                self.client._mark_wait_acknowledged(WAIT_ATTR_TRACEROUTE, request_id=request_id)
            except Exception as e:
                result_lines.append(f"❌ Failed to parse response: {e}")
            finally:
                loop.call_soon_threadsafe(result_event.set)

        def run_traceroute():
            try:
                r      = mesh_pb2.RouteDiscovery()
                packet = self.client._send_data_with_wait(
                    r,
                    destinationId=dest,
                    portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
                    wantResponse=True,
                    onResponse=on_traceroute_response,
                    channelIndex=0,
                    hopLimit=hop_limit,
                    response_wait_attr=WAIT_ATTR_TRACEROUTE,
                )
                with self.client._node_db_lock:
                    node_count = len(self.client.nodes) if self.client.nodes else 0
                nodes_factor = (node_count - 1) if node_count else (hop_limit + 1)
                wait_factor  = max(1, min(nodes_factor, hop_limit + 1))
                request_id   = self.client._extract_request_id_from_sent_packet(packet)
                self.client.waitForTraceRoute(wait_factor, request_id=request_id)
            except Exception as e:
                result_lines.append(f"❌ Traceroute error: {e}")
                loop.call_soon_threadsafe(result_event.set)

        async def run_and_report():
            await loop.run_in_executor(None, run_traceroute)
            try:
                await asyncio.wait_for(result_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            msg = "\n\n".join(result_lines) if result_lines else f"⚠️ No response from `{dest}`."
            await self.send_matrix_message(
                room.room_id, msg, reply_to_event_id=event.event_id,
            )

        asyncio.create_task(run_and_report())
        return True
