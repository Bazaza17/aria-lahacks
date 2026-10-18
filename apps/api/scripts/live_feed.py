"""Play a fire drill through the CREAO layer, as Sai's Photon + ElevenLabs pipeline would send it.

Everything goes through the real endpoints: occupants are registered, a dispatcher declares the
drill with a fire model (simulation), and texts and call lines arrive as /live/intake/events
envelopes. Some people never reply, so the 60 s chase kicks in. Watch it live with:

    curl -N "http://localhost:8000/live/stream?building_id=547b5ec5-30c5-4f76-8080-012a52e90bd9"

    uv run python scripts/live_feed.py                   # play the drill
    uv run python scripts/live_feed.py --approve         # also approve the first route change, as a dispatcher
"""

import argparse
import asyncio
import os
import random
import uuid

import httpx

VENUE = "547b5ec5-30c5-4f76-8080-012a52e90bd9"  # James West Alumni Center
NAMES = [
    "Ana",
    "Ben",
    "Chloe",
    "Dev",
    "Eli",
    "Fatima",
    "Gus",
    "Hana",
    "Ivan",
    "Jade",
    "Kofi",
    "Lena",
    "Mateo",
    "Nia",
    "Omar",
    "Priya",
    "Quinn",
    "Rosa",
    "Sam",
    "Tariq",
    "Uma",
    "Vik",
    "Wren",
    "Zoe",
]
ZONES = ["Collins Room", "galleria", "Founders' Room", "Collins Patio", "networking", None]
FIRE_MODEL = {
    "label": "Galleria fire (simulation)",
    "steps": [
        {"minute": 0, "place": "galleria", "kind": "fire"},
        {"minute": 4, "place": "galleria far end", "kind": "smoke"},
        {"minute": 8, "place": "restrooms", "kind": "smoke"},
    ],
}


class Pipeline:
    def __init__(self, base: str) -> None:
        headers = {}
        if secret := os.environ.get("CREAO_TOOL_SECRET"):
            headers["X-Tool-Secret"] = secret
        if key := next(iter(os.environ.get("DISPATCH_API_KEYS", "").split(",")), ""):
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.AsyncClient(base_url=f"{base}/live", headers=headers, timeout=30)

    async def event(self, kind: str, **payload) -> dict:
        r = await self.http.post(
            "/intake/events",
            json={
                "eventId": uuid.uuid4().hex,
                "eventType": kind,
                "source": "photon",
                "payload": {"buildingId": VENUE, **payload},
            },
        )
        r.raise_for_status()
        return r.json()

    async def text(self, phone: str, text: str) -> dict:
        out = await self.event("sms.received", phone=phone, text=text)
        reply = (out.get("reply") or {}).get("instruction", {}).get("message")
        if reply:  # the pipeline texts back the approved instruction, nothing else
            await self.event("sms.sent", phone=phone, text=reply)
        return out


async def call(
    p: Pipeline, phone: str, lines: list[str], details: dict | None = None, gap: float = 3
) -> None:
    conv = f"conv_{uuid.uuid4().hex[:10]}"
    await p.event("call.started", conversationId=conv, phone=phone)
    for i, line in enumerate(lines):
        await p.event("call.transcript", conversationId=conv, phone=phone, role="user", text=line)
        if i == 0 and details:
            await p.event("call.details", conversationId=conv, phone=phone, **details)
        await asyncio.sleep(gap)


async def main(base: str, approve: bool) -> None:
    random.seed(4)
    p = Pipeline(base)
    people = [
        {
            "phone": f"+1555500{i:04d}",
            "name": n,
            **({"zone": ZONES[i % len(ZONES)]} if ZONES[i % len(ZONES)] else {}),
        }
        for i, n in enumerate(NAMES)
    ]
    people[3]["mobility"] = ["wheelchair"]
    await p.http.post(f"/buildings/{VENUE}/occupants", json={"people": people})
    r = await p.http.post(
        f"/buildings/{VENUE}/evacuations",
        json={
            "mode": "drill",
            "origin": "galleria",
            "dispatcher": "AP",
            "fire_model": FIRE_MODEL,
            "description": "Fire drill: fire in the Galleria",
        },
    )
    drill = r.json()
    print(f"DRILL declared · {len(drill['recipients'])} alerted")
    for x in drill["recipients"]:
        await p.event(
            "sms.sent", phone=x["phone"], text=x["message"]
        )  # Photon texted the approved route

    async def fire_call():
        await call(
            p,
            people[0]["phone"],
            [
                "There's fire in the galleria by the sponsor booths and smoke is spreading",
                "I'm heading out through the main entrance now",
            ],
            details={
                "description": "Fire in the Galleria, smoke spreading",
                "zone": "galleria",
                "urgency": "critical",
            },
        )

    async def trapped_call():
        await asyncio.sleep(12)
        await call(
            p,
            people[8]["phone"],
            ["I'm trapped in the restroom, the door won't open and there's smoke"],
        )

    async def texts():
        await asyncio.sleep(4)
        await p.text(
            people[3]["phone"],
            "HELP I'm in the Founders' Room in my wheelchair and the patio doors are blocked",
        )
        await asyncio.sleep(4)
        await p.text(people[20]["phone"], "the galleria back doors are jammed shut")
        order = [i for i in range(len(people)) if i not in (0, 3, 8, 20)]
        random.shuffle(order)
        for n, i in enumerate(order):
            if n % 6 == 5:
                continue  # never replies: stays UNCONFIRMED and gets chased after 60 s
            out = await p.text(
                people[i]["phone"], random.choice(["leaving now", "on my way out", "heading out"])
            )
            await asyncio.sleep(random.uniform(1, 2.5))
            if n % 3:
                await p.text(people[i]["phone"], "SAFE")
            if n == 2:
                print(
                    f"  reply to {people[i]['name']}: {(out.get('reply') or {}).get('instruction', {}).get('message')}"
                )

    async def dispatcher():
        if not approve:
            return
        for _ in range(30):
            await asyncio.sleep(3)
            props = (await p.http.get(f"/buildings/{VENUE}/route-proposals")).json()
            if props:
                d = (
                    await p.http.post(
                        f"/route-proposals/{props[0]['id']}/decision",
                        json={"decision": "approve", "dispatcher": "AP"},
                    )
                ).json()
                print(
                    f"  dispatcher approved {props[0]['zone_label']} -> {props[0]['to_exit_label']} "
                    f"({len(d.get('recipients', []))} re-texted)"
                )
                for x in d.get("recipients", []):
                    await p.event("sms.sent", phone=x["phone"], text=x["message"])
                return

    await asyncio.gather(fire_call(), trapped_call(), texts(), dispatcher())
    print("Feed done. Silent people are chased after 60 s; the CREAO staff keeps working.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument(
        "--approve", action="store_true", help="approve the first route change as dispatcher AP"
    )
    args = ap.parse_args()
    asyncio.run(main(args.base, args.approve))
