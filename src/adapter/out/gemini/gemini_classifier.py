"""Google Gemini Structured Outputs adapter (`google-genai` SDK) with strict Pydantic `response_schema`."""

from google import genai
from google.genai import types

from src.application.ports import LlmClassificationResponse


class GeminiStructuredClassifierAdapter:
    """
    Adapter for `LlmClassifierPort` using `google-genai` with `response_mime_type="application/json"`
    and strict Pydantic `response_schema=LlmClassificationResponse`.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    def classify_merchant(
        self,
        tenant_id: str,
        raw_description: str,
        merchant_clean: str,
        city: str | None,
        amount_str: str,
    ) -> LlmClassificationResponse:
        prompt = (
            "Classifique o lançamento de cartão de crédito brasileiro na Taxonomia Oficial de 2 Níveis.\n"
            f"Descrição bruta: {raw_description}\n"
            f"Estabelecimento limpo: {merchant_clean}\n"
            f"Município extraído: {city or 'N/A'}\n"
            f"Valor: R$ {amount_str}\n"
        )
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LlmClassificationResponse,
                temperature=0.0,
            ),
        )
        if not response.text:
            raise ValueError("Empty structured response from Gemini")
        return LlmClassificationResponse.model_validate_json(response.text)
