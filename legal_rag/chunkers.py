from typing import List, Dict, Any
import re
from .models import DocumentMetadata
from .config import DOMAIN


# ─────────────────────────────────────────────────────────────
# Patterns (optionnels, utilisés seulement comme signaux)
# ─────────────────────────────────────────────────────────────
DOMAIN_PATTERNS = {
    "legal": {
        'procedure': r'(?:Sur le pourvoi|Vu le pourvoi)',
        'recevabilite': r'Sur la recevabilité',
        'motifs': r'(?:Considérant que|Attendu que)',
        'dispositif': r'PAR CES MOTIFS',
    },
    "tourisme": {
        'hotel': r'(HÔTEL|HOTEL|AUBERGE|RÉSIDENCE|MÔTEL)',
    }
}


# ─────────────────────────────────────────────────────────────
# CHUNKER GÉNÉRALISTE ROBUSTE
# ─────────────────────────────────────────────────────────────
class StructuralChunker:

    def __init__(
        self,
        max_chunk_size: int = 1500,  # ✅ FIXED: 800 → 1500 (+87%) — keep semantic units together
        min_chunk_size: int = 300,   # ✅ FIXED: 200 → 300 (+50%) — avoid tiny fragments
        overlap: int = 400,          # ✅ FIXED: 120 → 400 (+233%) — preserve context at boundaries
        domain: str = None
    ):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap = overlap

        active_domain = domain or DOMAIN
        self.section_patterns = DOMAIN_PATTERNS.get(active_domain, {})

        print(f"🗂️ Chunker initialisé — domaine: {active_domain}")

    # ─────────────────────────────────────────────────────────
    # ENTRY POINT
    # ─────────────────────────────────────────────────────────
    def chunk_document(self, text: str, metadata: DocumentMetadata) -> List[Dict]:

        print(f"✂️ Chunking document: {len(text)} chars")

        # petit doc → un seul chunk
        if len(text) < self.max_chunk_size:
            return [{
                "text": text,
                "metadata": metadata,
                "chunk_type": "full_document",
                "chunk_index": 0
            }]

        # 1. split en blocs naturels
        blocks = self._split_into_blocks(text)

        # 2. fusion intelligente
        chunks = self._merge_blocks(blocks)

        # 3. format final
        return [
            {
                "text": chunk,
                "metadata": metadata,
                "chunk_type": "general",
                "chunk_index": i
            }
            for i, chunk in enumerate(chunks)
        ]

    # ─────────────────────────────────────────────────────────
    # 1. SPLIT PAR STRUCTURE NATURELLE
    # ─────────────────────────────────────────────────────────
    def _split_into_blocks(self, text: str) -> List[str]:

        # priorité : paragraphes
        blocks = re.split(r'\n\s*\n', text)

        cleaned = []
        for b in blocks:
            b = b.strip()
            if len(b) > 0:
                cleaned.append(b)

        return cleaned

    # ─────────────────────────────────────────────────────────
    # 2. MERGE INTELLIGENT DES BLOCS
    # ─────────────────────────────────────────────────────────
    def _merge_blocks(self, blocks: List[str]) -> List[str]:

        chunks = []
        current = ""

        for block in blocks:

            # si trop grand → split direct
            if len(block) > self.max_chunk_size:
                chunks.extend(self._split_large_block(block))
                continue

            # fusion normale
            if len(current) + len(block) <= self.max_chunk_size:
                current += "\n" + block
            else:
                chunks.append(current.strip())

                # overlap intelligent (phrases)
                current = self._create_overlap(current) + "\n" + block

        if current.strip():
            chunks.append(current.strip())

        return chunks

    # ─────────────────────────────────────────────────────────
    # 3. SPLIT GROS BLOC
    # ─────────────────────────────────────────────────────────
    def _split_large_block(self, text: str) -> List[str]:

        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current = ""

        for s in sentences:

            if len(current) + len(s) <= self.max_chunk_size:
                current += " " + s
            else:
                chunks.append(current.strip())
                current = self._create_overlap(current) + " " + s

        if current.strip():
            chunks.append(current.strip())

        return chunks

    # ─────────────────────────────────────────────────────────
    # 4. OVERLAP PROPRE (PHRASES)
    # ─────────────────────────────────────────────────────────
    def _create_overlap(self, text: str) -> str:

        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        if len(sentences) <= 2:
            return text[-self.overlap:]

        return " ".join(sentences[-2:])


# ─────────────────────────────────────────────────────────────
# CHUNKER MARKDOWN — pour sortie pymupdf4llm
# Découpe sur les titres (# ## ###) pour garder chaque section
# (hôtel, activité, lieu) dans un chunk cohérent.
# ─────────────────────────────────────────────────────────────
class MarkdownChunker:

    def __init__(
        self,
        max_chunk_size: int = 1500,
        min_chunk_size: int = 150,
        overlap: int = 300,
    ):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap = overlap
        # Correspond à ## Titre ou # Titre (niveaux 1–3)
        self._heading_re = re.compile(r'^#{1,3}\s+', re.MULTILINE)

    def chunk_document(self, text: str, metadata: DocumentMetadata) -> List[Dict]:
        print(f"✂️ MarkdownChunker: {len(text)} chars")

        if len(text) < self.max_chunk_size:
            return [{"text": text, "metadata": metadata, "chunk_type": "full_document", "chunk_index": 0}]

        sections = self._split_on_headings(text)
        chunks = self._merge_sections(sections)

        return [
            {"text": chunk, "metadata": metadata, "chunk_type": "markdown_section", "chunk_index": i}
            for i, chunk in enumerate(chunks)
        ]

    def _split_on_headings(self, text: str) -> List[str]:
        """Découpe le texte aux titres Markdown tout en les conservant."""
        parts = self._heading_re.split(text)
        headings = self._heading_re.findall(text)

        sections = []
        # premier bloc avant tout titre
        if parts[0].strip():
            sections.append(parts[0].strip())

        for heading, body in zip(headings, parts[1:]):
            section = (heading + body).strip()
            if section:
                sections.append(section)

        return sections or [text]

    @staticmethod
    def _is_heading(text: str) -> bool:
        return text.lstrip().startswith('#')

    def _merge_sections(self, sections: List[str]) -> List[str]:
        """
        Règle : chaque section qui commence par un titre ## (hôtel, restaurant, lieu…)
        devient son propre chunk — on ne fusionne JAMAIS deux sections titrées ensemble.
        Le texte d'intro (avant le premier titre) peut être attaché à la première section.
        """
        chunks = []
        current = ""

        for section in sections:
            if len(section) > self.max_chunk_size:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._split_large(section))
                continue

            if not current:
                current = section
            elif self._is_heading(section):
                # Nouvelle section titrée → toujours sauvegarder et repartir seul
                chunks.append(current.strip())
                current = section
            elif len(current) + len(section) + 2 <= self.max_chunk_size:
                # Texte de suite (non titré) → fusionner avec la section courante
                current = current + "\n\n" + section
            else:
                chunks.append(current.strip())
                current = section

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _split_large(self, text: str) -> List[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, current = [], ""
        for s in sentences:
            if len(current) + len(s) <= self.max_chunk_size:
                current = (current + " " + s).strip()
            else:
                if current:
                    chunks.append(current)
                current = s
        if current:
            chunks.append(current)
        return chunks