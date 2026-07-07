# Events

Internal event bus for decoupled bot communication.

Hokage publishes workflow events; bots subscribe and respond. User-facing messages always flow through Hokage.

## Implementation
The subfolder exists as an integration point for future event-driven architecture, while current bot coordination is managed synchronously by the central orchestrator.
