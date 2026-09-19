"""Provider plugins — the seams where AlphaDesk talks to the outside world.

Three things are pluggable: the news feed, market data, and the earnings
transcript source. Each is a
Protocol in `base`, an implementation registered by name, and a config key that
picks which one runs. Nothing in the app imports a vendor directly any more; it
asks the registry.

Third-party packages plug in without touching this repo — see
`docs/providers.md`.
"""

from alphadesk.providers.base import (  # noqa: F401
    Article,
    NewsProvider,
    PriceProvider,
    ProviderError,
    TranscriptProvider,
)
from alphadesk.providers.registry import (  # noqa: F401
    available,
    get_prices,
    get_transcripts,
    register,
)
