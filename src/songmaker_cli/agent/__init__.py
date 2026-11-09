"""The co-writer's turn through the LiteLLM gateway.

``tools`` serves the co-writer's tools to the turn as the client's hand tools; ``backend``
composes the gateway backend once at startup and runs one turn for one person;
``route_decisions`` is where a route takes its decision as an agent tool.
"""
