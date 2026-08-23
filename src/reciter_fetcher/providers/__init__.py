from reciter_fetcher.providers.everyayah import EveryAyahProvider
from reciter_fetcher.providers.mp3quran import Mp3QuranProvider
from reciter_fetcher.providers.quran_foundation import QuranFoundationProvider

PROVIDERS = {
    "quran-foundation": QuranFoundationProvider,
    "mp3quran": Mp3QuranProvider,
    "everyayah": EveryAyahProvider,
}

