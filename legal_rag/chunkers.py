from typing import List, Dict, Any
import re
from .models import DocumentMetadata
from .config import DOMAIN

# ── Patterns de sections par domaine ────────────────────────────────────────
DOMAIN_PATTERNS = {
    "legal": {
        'procedure':       r'(?:Sur le pourvoi|Vu le pourvoi)',
        'recevabilite':    r'Sur la recevabilité',
        'motifs':          r'(?:Sur le fond|Attendu que|Considérant que)',
        'dispositif':      r'PAR CES MOTIFS',
        'formule_finale':  r'Ainsi (?:fait|jugé)',
    },
    "municipal": {
        'objet':           r'(?:OBJET\s*:|Objet\s*:)',
        'vu':              r'\bVU\b(?:\s+le|\s+la|\s+l\'|\s+les|\s+que)',
        'considerant':     r'\bCONSIDÉRANT\b|\bConsidérant\b',
        'decide':          r'(?:DÉCIDE\b|LE CONSEIL MUNICIPAL\b|Le Conseil Municipal\b)',
        'article':         r'(?:ARTICLE\s+\d+|Article\s+\d+)\s*[-–:]',
        'arrete':          r'(?:ARRÊTE\s*:|LE MAIRE\s*,|Le Maire\s*,)',
        'deliberation':    r'(?:DÉLIBÉRATION|Délibération)\s+n°',
        'vote':            r'(?:Résultat du vote|Vote\s*:)',
    },
    "medical": {
        'patient':         r'(?:Patient\s*:|Nom\s*:)',
        'diagnostic':      r'(?:Diagnostic\s*:|Conclusion\s*:)',
        'traitement':      r'(?:Traitement\s*:|Prescription\s*:)',
        'antecedents':     r'(?:Antécédents\s*:|ATCD\s*:)',
        'examen':          r'(?:Examen clinique|Résultats\s*:)',
    },
    "rh": {
        'poste':           r'(?:Intitulé du poste|Poste\s*:)',
        'missions':        r'(?:Missions\s*:|Responsabilités\s*:)',
        'profil':          r'(?:Profil recherché|Compétences\s*:)',
        'conditions':      r'(?:Conditions\s*:|Rémunération\s*:)',
    },
    "technique": {
        'objectif':        r'(?:Objectif\s*:|But\s*:)',
        'description':     r'(?:Description\s*:|Présentation\s*:)',
        'specification':   r'(?:Spécification|Cahier des charges)',
        'conclusion':      r'(?:Conclusion\s*:|Résumé\s*:)',
    },
}


class StructuralLegalChunker:
    """
    Chunker structurel multi-domaine.

    Stratégie :
    1. Détection des sections par patterns du domaine configuré
    2. Chunking par section (si taille OK)
    3. Fallback récursif si section trop longue
    """

    def __init__(
        self,
        max_chunk_size: int = 800,
        min_chunk_size: int = 100,
        overlap: int = 100,
        domain: str = None
    ):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap = overlap

        # Domaine : paramètre explicite > config globale > fallback legal
        active_domain = domain or DOMAIN
        self.section_patterns = DOMAIN_PATTERNS.get(active_domain, DOMAIN_PATTERNS["legal"])
        print(f"  🗂️  Chunker initialisé — domaine : {active_domain.upper()}")

    def chunk_document(
        self,
        text: str,
        metadata: DocumentMetadata
    ) -> List[Dict[str, Any]]:
        """
        Chunking adaptatif d'un document.

        Returns:
            Liste de dicts {text, metadata, chunk_type, chunk_index}
        """
        print(f"  ✂️  Chunking: {len(text)} chars...")

        if len(text) < self.max_chunk_size * 2:
            print(f"    → Document court: chunk unique")
            return [{
                'text': text,
                'metadata': metadata,
                'chunk_type': 'full_document',
                'chunk_index': 0
            }]

        sections = self._detect_sections(text)

        if sections:
            print(f"    → {len(sections)} sections détectées")
            return self._chunk_by_sections(sections, text, metadata)

        print(f"    → Fallback: chunking récursif")
        return self._recursive_chunk(text, metadata)

    def _detect_sections(self, text: str) -> List[Dict]:
        sections = []
        for section_type, pattern in self.section_patterns.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                sections.append({
                    'type': section_type,
                    'start': match.start(),
                    'marker': match.group(0)
                })
        sections.sort(key=lambda x: x['start'])
        for i, section in enumerate(sections):
            if i < len(sections) - 1:
                section['end'] = sections[i + 1]['start']
            else:
                section['end'] = len(text)
        return sections if len(sections) >= 2 else []

    def _chunk_by_sections(
        self,
        sections: List[Dict],
        text: str,
        metadata: DocumentMetadata
    ) -> List[Dict]:
        chunks = []
        for idx, section in enumerate(sections):
            section_text = text[section['start']:section['end']].strip()
            if len(section_text) > self.max_chunk_size:
                sub_chunks = self._recursive_chunk_text(section_text)
                for sub_idx, sub_chunk in enumerate(sub_chunks):
                    chunks.append({
                        'text': sub_chunk,
                        'metadata': metadata,
                        'chunk_type': section['type'],
                        'chunk_index': f"{idx}.{sub_idx}",
                        'section_marker': section['marker']
                    })
            else:
                chunks.append({
                    'text': section_text,
                    'metadata': metadata,
                    'chunk_type': section['type'],
                    'chunk_index': idx,
                    'section_marker': section['marker']
                })
        return chunks

    def _recursive_chunk(
        self,
        text: str,
        metadata: DocumentMetadata
    ) -> List[Dict]:
        chunks_text = self._recursive_chunk_text(text)
        return [
            {
                'text': chunk,
                'metadata': metadata,
                'chunk_type': 'recursive',
                'chunk_index': idx
            }
            for idx, chunk in enumerate(chunks_text)
        ]

    def _recursive_chunk_text(self, text: str) -> List[str]:
        separators = ['\n\n', '\n', '. ', '; ', ', ']
        return self._split_recursive(text, separators)

    def _split_recursive(self, text: str, seps: List[str]) -> List[str]:
        if not seps or len(text) <= self.max_chunk_size:
            return [text] if text.strip() else []
        sep = seps[0]
        splits = text.split(sep)
        chunks = []
        current = []
        current_len = 0
        for split in splits:
            split_len = len(split) + len(sep)
            if split_len > self.max_chunk_size:
                if current:
                    chunks.append(sep.join(current))
                    current = []
                    current_len = 0
                sub_chunks = self._split_recursive(split, seps[1:])
                chunks.extend(sub_chunks)
                continue
            if current_len + split_len > self.max_chunk_size and current:
                chunks.append(sep.join(current))
                overlap_text = sep.join(current)[-self.overlap:]
                current = [overlap_text, split]
                current_len = len(overlap_text) + split_len
            else:
                current.append(split)
                current_len += split_len
        if current:
            chunks.append(sep.join(current))
        return [c.strip() for c in chunks if c.strip()]
