"""Layer 2: Deterministic Acquirer Prefix Stripper, City Extractor & Keyword Classifier."""

import re

from src.domain.models import NormalizationResult
from src.domain.taxonomy import CategoryCode

# Acquirer and sub-acquirer prefixes commonly found on Itaú/BB/Marisa statements
_ACQUIRER_PREFIX_PATTERN = re.compile(
    r"^\s*(?P<prefix>"
    r"JIM\.COM\s*\*|"
    r"MP\s*\*|"
    r"BMB\s*\*|"
    r"HNA\s*\*|"
    r"PG\s*\*|"
    r"EC\s*\*|"
    r"PAG\s*\*|"
    r"PAGSEGURO\s*\*|"
    r"STONE\s*\*|"
    r"SUMUP\s*\*|"
    r"C6PAY\s*\*|"
    r"IFD\s*\*"
    r")\s*",
    re.IGNORECASE,
)

# Installment tokens embedded in raw descriptions (e.g., "02/10" or "PARC 02/10")
_INSTALLMENT_SUFFIX_PATTERN = re.compile(
    r"\s+(?:PARC\s*)?\d{2}/\d{2}\s*$",
    re.IGNORECASE,
)

# Known Brazilian municipality suffixes glued or spaced at the end of card descriptors
# Supports glued ISO/country/state suffixes like "ACUBRA", "NATALBRA", "MOSSOROBRA", "SAO PAULOBR"
_KNOWN_CITIES_MAP: dict[str, str] = {
    "ACU": "Acu",
    "ASSU": "Acu",
    "NATAL": "Natal",
    "MOSSORO": "Mossoro",
    "CAICO": "Caico",
    "PARNAMIRIM": "Parnamirim",
    "MACAU": "Macau",
    "FORTALEZA": "Fortaleza",
    "RECIFE": "Recife",
    "SAO PAULO": "Sao Paulo",
    "SAOPAULO": "Sao Paulo",
    "CURITIBA": "Curitiba",
    "BRASILIA": "Brasilia",
    "BELO HORIZONTE": "Belo Horizonte",
    "RIO DE JANEIRO": "Rio de Janeiro",
}

# Ordered deterministic rules: high-specificity rules BEFORE generic ones
# Note: CHURRASCARIA is evaluated before SUPERMERCADO so that "CHURRASCARIA GAUCHA"
# is never misclassified as Supermercado even if an upstream hint or substring suggested grocery.
_DETERMINISTIC_KEYWORD_RULES: list[tuple[str, re.Pattern[str], CategoryCode, float]] = [
    (
        "BANK_FEE_AVISA_ANUIDADE",
        re.compile(r"\b(ITAU\s+AVISA|MENSALIDADE\s+AVISA|ANUIDADE|TARIFA\s+BANCARIA|AVAL\s+EMERG)\b", re.IGNORECASE),
        CategoryCode.DEBT_BANK_FEE,
        0.99,
    ),
    (
        "IOF_INTEREST",
        re.compile(r"\b(IOF|JUROS\s+DE\s+MORA|ENCARGOS\s+ROTATIVO|MULTA\s+ATRASO)\b", re.IGNORECASE),
        CategoryCode.DEBT_INTEREST_IOF,
        0.99,
    ),
    (
        "REFUND_ESTORNO",
        re.compile(r"\b(ESTORNO|CREDITO\s+FATURA|DEVOLUCAO|CASHBACK)\b", re.IGNORECASE),
        CategoryCode.INC_REFUND_CASHBACK,
        0.98,
    ),
    (
        "RESTAURANT_STEAKHOUSE",
        re.compile(
            r"\b(CHURRASCARIA|RESTAURANTE|PIZZARIA|HAMBURGUERIA|LANCHONETE|PADARIA|PANIFICADORA|BISTRO|SUSHI|BAR\s+E\s+REST)\b",
            re.IGNORECASE,
        ),
        CategoryCode.VAR_FOOD_RESTAURANT,
        0.96,
    ),
    (
        "FOOD_DELIVERY",
        re.compile(r"\b(IFOOD|RAPPI|ZE\s+DELIVERY|AIQFOME)\b", re.IGNORECASE),
        CategoryCode.VAR_FOOD_DELIVERY,
        0.96,
    ),
    (
        "FUEL_STATION",
        re.compile(r"\b(POSTO|AUTO\s+POSTO|PETROBRAS|SHELL\s+BOX|IPIRANGA|COMBUSTIVEIS)\b", re.IGNORECASE),
        CategoryCode.VAR_MOBILITY_FUEL,
        0.95,
    ),
    (
        "MOBILITY_APP",
        re.compile(r"\b(UBER|99APP|99\s*\*|99\s+POP|INDDRIVER|SEM\s+PARAR|VELOE|CONECTCAR)\b", re.IGNORECASE),
        CategoryCode.VAR_MOBILITY_APP,
        0.94,
    ),
    (
        "PHARMACY_HEALTH_CARE",
        re.compile(
            r"\b(DROGARIA|FARMACIA|PAGUE\s+MENOS|DROGASIL|RAIA|ULTRAFARMA|PANVEL|EXTRAFARMA|CLINICA|LABORATORIO)\b",
            re.IGNORECASE,
        ),
        CategoryCode.VAR_FAMILY_CARE,
        0.95,
    ),
    (
        "GROCERY_SUPERMARKET",
        re.compile(
            r"\b(SUPERMERCADO|MERCADINHO|ATACADAO|ASSAI|CARREFOUR|PAO\s+DE\s+ACUCAR|HIPERMERCADO|FRIGORIFICO|HORTIFRUTI)\b",
            re.IGNORECASE,
        ),
        CategoryCode.VAR_FOOD_GROCERY,
        0.93,
    ),
    (
        "DIGITAL_SUBSCRIPTIONS",
        re.compile(r"\b(NETFLIX|SPOTIFY|AMAZON\s+PRIME|DISNEY\s*PLUS|HBO\s*MAX|YOUTUBE\s+PREMIUM|OPENAI|CLAUDE|GOOGLE\s+ONE|APPLE\.COM/BILL)\b", re.IGNORECASE),
        CategoryCode.VAR_SUBSCRIPTIONS,
        0.96,
    ),
    (
        "PET_CARE",
        re.compile(r"\b(PETZ|COBASI|PETLOVE|PET\s+SHOP|CLINICA\s+VETERINARIA|VET\b)\b", re.IGNORECASE),
        CategoryCode.VAR_PET_CARE,
        0.94,
    ),
    (
        "UTILITIES_TELECOM",
        re.compile(r"\b(COSERN|NEOENERGIA|CAERN|SABESP|ENEL|CEMIG|CLARO|VIVO|TIM\s+S\s*A|BRISANET)\b", re.IGNORECASE),
        CategoryCode.FIX_UTILITIES,
        0.95,
    ),
]


class MerchantNormalizer:
    """Pure domain Layer 2 normalizer for Brazilian credit card descriptors."""

    def normalize(self, raw_description: str) -> NormalizationResult:
        """
        1. Strip acquirer prefix (JIM.COM*, MP *, BMB*, HNA*, PG *, EC *, PAG*).
        2. Strip trailing installment tokens (01/10).
        3. Extract glued or trailing city/country suffix (e.g. POSTO FREI DAMIAOACUBRA -> POSTO FREI DAMIAO + Acu).
        4. Apply deterministic keyword rules with confidence scoring.
        """
        working = raw_description.strip().upper()
        acquirer_prefix: str | None = None

        # Step 1: Extract and strip acquirer prefix
        prefix_match = _ACQUIRER_PREFIX_PATTERN.match(working)
        if prefix_match:
            raw_prefix = prefix_match.group("prefix")
            acquirer_prefix = re.sub(r"\s+", " ", raw_prefix).strip()
            working = working[prefix_match.end() :].strip()

        # Step 2: Remove trailing installment pattern if present
        working = _INSTALLMENT_SUFFIX_PATTERN.sub("", working).strip()

        # Step 3: Extract glued or spaced City + BRA/BR/UF suffix
        merchant_clean, city, country_or_state = self._extract_city_and_clean_merchant(working)

        # Normalize whitespace
        merchant_clean = re.sub(r"\s+", " ", merchant_clean).strip()

        # Step 4: Match deterministic keyword rules
        for rule_name, pattern, category_code, confidence in _DETERMINISTIC_KEYWORD_RULES:
            if pattern.search(merchant_clean):
                return NormalizationResult(
                    raw_description=raw_description,
                    acquirer_prefix=acquirer_prefix,
                    merchant_clean=merchant_clean,
                    city=city,
                    country_or_state=country_or_state,
                    matched_category=category_code,
                    confidence=confidence,
                    rule_matched=rule_name,
                )

        return NormalizationResult(
            raw_description=raw_description,
            acquirer_prefix=acquirer_prefix,
            merchant_clean=merchant_clean,
            city=city,
            country_or_state=country_or_state,
            matched_category=None,
            confidence=0.0,
            rule_matched=None,
        )

    @staticmethod
    def _extract_city_and_clean_merchant(text: str) -> tuple[str, str | None, str | None]:
        """
        Detect glued or separated city + country/state code at the end of descriptor.
        Example: 'POSTO FREI DAMIAOACUBRA' -> ('POSTO FREI DAMIAO', 'Acu', 'BRA')
        """
        # Sort cities by length descending so longer names match first
        for city_token, canonical_city in sorted(
            _KNOWN_CITIES_MAP.items(), key=lambda item: len(item[0]), reverse=True
        ):
            # Case A: Glued or spaced city + country/UF suffix (e.g., "DAMIAOACUBRA" or "DAMIAO ACU BRA" or "DAMIAO ACU RN")
            glued_pattern = re.compile(
                rf"^(?P<merchant>.+?)\s*{re.escape(city_token)}\s*(?P<country>BRA|BR|RN|SP|RJ|CE|PE|MG|DF|PR|RS)?$",
                re.IGNORECASE,
            )
            match = glued_pattern.match(text)
            if match:
                candidate_merchant = match.group("merchant").strip(" -*/")
                country = match.group("country")
                # Require either a country/UF suffix (like BRA/RN) OR space separation so we don't strip random word endings
                if (country or text.endswith(f" {city_token}")) and len(candidate_merchant) >= 3:
                    return candidate_merchant, canonical_city, country or "BRA"

        return text, None, None
