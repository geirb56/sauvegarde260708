"""Garmin connector package (invisible, OAuth-like experience).

All Garmin-specific logic is encapsulated inside this package behind a
Provider abstraction. No Garmin logic must exist outside this layer.

- providers/      : Provider abstraction + real Gccli implementation
- runner.py       : Isolated GccliRunner (encapsulates the gccli binary)
- factory.py      : Returns the gccli provider
- service.py       : Orchestration (connect / sync / status / disconnect)
"""
