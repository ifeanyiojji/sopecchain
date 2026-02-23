"""
PDF Extraction Module.
Extracts operational data from PDF invoices/tickets using Claude Vision API.
"""
import os
import json
import base64
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from anthropic import Anthropic, APIError, RateLimitError
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class PDFExtractor:
    """
    PDF extractor using Claude Vision API for data extraction.
    Processes pages sequentially for compatibility with sync/async contexts.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        dpi: int = 150,
        model: str = "claude-sonnet-4-5-20250929"
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.dpi = dpi
        self.model = model

        if HAS_ANTHROPIC and self.api_key:
            self.client = Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def is_available(self) -> bool:
        """Check if PDF extraction is available (API key + dependencies)."""
        return bool(self.client and HAS_FITZ)

    def extract_from_bytes(self, pdf_bytes: bytes) -> pd.DataFrame:
        """
        Extract data from PDF bytes.

        Args:
            pdf_bytes: Raw PDF file content

        Returns:
            DataFrame with extracted operational data
        """
        if not self.is_available():
            return pd.DataFrame()

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        results = []

        for page_num in range(total_pages):
            try:
                page = doc[page_num]
                pix = page.get_pixmap(dpi=self.dpi)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()

                data = self._extract_page(img_b64, page_num + 1)
                if data:
                    data["source"] = f"PDF_page_{page_num + 1}"
                    results.append(data)
            except Exception as e:
                print(f"Page {page_num + 1} extraction failed: {str(e)[:100]}")

        doc.close()

        print(f"Extracted {len(results)}/{total_pages} pages successfully")
        return pd.DataFrame(results) if results else pd.DataFrame()

    def _extract_page(self, image_b64: str, page_num: int) -> Optional[Dict[str, Any]]:
        """Extract data from a single page image."""
        prompt = self._build_prompt()

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }]
            )

            text = response.content[0].text.strip()
            return self._parse_json(text)

        except Exception as e:
            print(f"API error on page {page_num}: {e}")
            return None

    def _build_prompt(self) -> str:
        return """Extract numeric operational data from this field ticket or invoice.
Return ONLY valid JSON - no commentary, no markdown code blocks.

Allowed keys (include only if value exists):
- date: Operation date (YYYY-MM-DD format if possible)
- diesel_l: Diesel fuel in liters
- diesel_gal: Diesel fuel in gallons (if specified in gallons)
- water_bbl: Water volume in barrels
- water_m3: Water volume in cubic meters
- oil_bbl: Oil production in barrels
- gas_mcf: Gas production in thousand cubic feet (MCF)
- distance_km: Hauling distance in kilometers
- vendor: Supplier/vendor name
- equipment_id: Equipment or truck ID
- ticket_number: Ticket/invoice number

Extraction rules:
1. Convert words to numbers ("two thousand" -> 2000)
2. Handle unit abbreviations (L, gal, bbl, m3, MCF)
3. If a value doesn't exist, OMIT the field entirely
4. Return ONLY JSON - no preamble, no code fences
5. Be aggressive in extraction - if you see a number near a unit, extract it

Example: {"date": "2024-03-15", "diesel_l": 2500, "water_bbl": 150, "vendor": "Halliburton"}"""

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end <= start:
            return None

        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            return None


# Singleton instance
_extractor: Optional[PDFExtractor] = None


def get_pdf_extractor() -> PDFExtractor:
    """Get or create the global PDF extractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = PDFExtractor()
    return _extractor
