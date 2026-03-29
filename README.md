# mcp-spain-travel

Multimodal travel search MCP server for Spain. Aggregates **Renfe GTFS schedules**, **OUIGO prices**, and **Amadeus flight offers** into four AI-ready tools for any MCP-compatible client (Claude Desktop, Continue, etc.).

## Installation

```bash
# Run directly with uv (recommended)
uvx mcp-spain-travel

# Or install with pip
pip install mcp-spain-travel
```

## Configuration

All settings are read from environment variables prefixed with `SPAIN_TRAVEL_`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SPAIN_TRAVEL_AMADEUS_CLIENT_ID` | Yes (flights) | `""` | Amadeus API client ID |
| `SPAIN_TRAVEL_AMADEUS_CLIENT_SECRET` | Yes (flights) | `""` | Amadeus API client secret |
| `SPAIN_TRAVEL_OUIGO_ENABLED` | No | `true` | Enable OUIGO price aggregation |
| `SPAIN_TRAVEL_STATIONS_TTL` | No | `86400` | Station cache TTL in seconds (24h) |
| `SPAIN_TRAVEL_OUIGO_TTL` | No | `1800` | OUIGO price cache TTL in seconds (30min) |
| `SPAIN_TRAVEL_AMADEUS_TTL` | No | `3600` | Amadeus flight cache TTL in seconds (1h) |
| `SPAIN_TRAVEL_CACHE_DIR` | No | `.cache` | Directory for file-based cache |
| `SPAIN_TRAVEL_LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

Get a free Amadeus API key at [developers.amadeus.com](https://developers.amadeus.com).

## Claude Desktop Setup

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "spain-travel": {
      "command": "uvx",
      "args": ["mcp-spain-travel"],
      "env": {
        "SPAIN_TRAVEL_AMADEUS_CLIENT_ID": "your_client_id",
        "SPAIN_TRAVEL_AMADEUS_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

## Tools Reference

| Tool | Description | Key Parameters |
|---|---|---|
| `search_trains` | Search trains combining Renfe GTFS + OUIGO prices | `origin`, `destination`, `date` (YYYY-MM-DD), `passengers` |
| `search_flights` | Search Amadeus flight offers between Spanish airports | `origin` (IATA), `destination` (IATA), `departure_date`, `return_date`, `adults`, `cabin_class` |
| `compare_travel_options` | Side-by-side train vs flight comparison with CO2 estimates | `origin`, `destination`, `date`, `passengers` |
| `list_train_stations` | Browse Renfe station catalog (24h cached) | `city` (optional filter), `station_type` (all/cercanias/feve/ld) |

### Example Queries

```
# Find trains Madrid → Barcelona tomorrow
search_trains(origin="Madrid", destination="Barcelona", date="2025-04-01")

# Search flights Seville → Bilbao
search_flights(origin="SVQ", destination="BIO", departure_date="2025-04-01")

# Compare all options Madrid → Valencia
compare_travel_options(origin="Madrid", destination="Valencia", date="2025-04-01")

# List AVE-capable stations
list_train_stations(station_type="ld")
```

### Error Codes

| Code | Trigger |
|---|---|
| `INVALID_DATE` | Date in the past or wrong format |
| `INVALID_IATA` | IATA code is not exactly 3 letters |
| `UNKNOWN_STATION` | No Renfe station matches the city/code |
| `RATE_LIMIT` | Amadeus API quota exceeded |
| `ALL_PROVIDERS_DOWN` | All data sources failed simultaneously |
| `PROVIDER_ERROR` | Single provider failed (check `provider_errors` field) |

## Data Sources

- **Renfe Open Data** — Station catalog and GTFS schedules via [Renfe public files](https://ssl.renfe.com). No pricing (schedules only).
- **OUIGO** — Prices via the unofficial [`ouigo`](https://pypi.org/project/ouigo/) Python package. Real-time but subject to availability.
- **Amadeus GDS** — Flight offers via the official [Amadeus for Developers](https://developers.amadeus.com) API. Free tier covers test data; production requires approval.

## Development

```bash
# Clone and set up
git clone https://github.com/your-org/mcp-spain-travel
cd mcp-spain-travel
uv sync --extra dev

# Run tests
uv run pytest tests/ -v

# Run server locally
SPAIN_TRAVEL_AMADEUS_CLIENT_ID=xxx SPAIN_TRAVEL_AMADEUS_CLIENT_SECRET=yyy uv run mcp-spain-travel
```

## Disclaimer

OUIGO data is fetched via an unofficial third-party package. This project is not affiliated with, endorsed by, or connected to OUIGO España, Renfe, or Amadeus IT Group. Use at your own risk. Train/flight data may be incomplete or outdated — always verify with official sources before booking.

## License

MIT
