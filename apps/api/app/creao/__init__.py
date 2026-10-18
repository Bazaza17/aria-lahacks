"""The CREAO layer: live incidents, exit tracking and the CREAO command staff.

While a fire (or a labeled drill) is happening, this layer:

- takes in what callers and texters say through Photon + ElevenLabs (Sai's pipeline posts
  normalized events to /live/intake/events) and turns it into incidents pinned on the scan,
  hazards, and a roll call;
- gives the dispatcher the live situation (pins by severity, which exits people use, who is
  unconfirmed) over REST and SSE, plus route approvals and human handoffs;
- runs the CREAO command staff: an Incident Commander and specialists, each a saved CREAO
  agent, who analyse, propose routes and write the live incident report through /mcp.

Nothing an agent does reaches occupants until a dispatcher approves it.
"""
