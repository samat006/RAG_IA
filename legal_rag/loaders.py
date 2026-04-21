import os
import re
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, List
from collections import Counter
from datetime import datetime
import fitz  # PyMuPDF


class PDFLoader:
    """
    Loader PDF adaptatif — fonctionne sur tout type de document :
    juridique, touristique, technique, magazine, rapport, etc.

    Stratégie :
    1. Détection automatique du type de mise en page (mono/multi-colonnes)
    2. Détection statistique des headers/footers répétitifs (pas de seuil fixe)
    3. Reconstruction du flux de lecture dans l'ordre naturel
    4. Nettoyage minimal : uniquement les lignes vraiment répétées sur N pages
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.metadata = {
            'source_file': os.path.basename(file_path),
            'source_type': 'pdf'
        }
        self.raw_text = ""
        self.pages_data = []

    def load(self) -> Dict[str, Any]:
        print(f"\n📄 Chargement PDF adaptatif: {self.file_path}")

        doc = fitz.open(self.file_path)
        self.metadata['num_pages'] = len(doc)

        # Passe 1 : extraire tous les blocs de toutes les pages
        all_pages_blocks = []
        for page_num, page in enumerate(doc, start=1):
            rect = page.rect
            blocks = page.get_text("blocks")
            all_pages_blocks.append({
                'page_num': page_num,
                'blocks': blocks,
                'width': rect.width,
                'height': rect.height
            })

        doc.close()

        # Passe 2 : détecter les lignes répétitives (headers/footers réels)
        repetitive_lines = self._detect_repetitive_lines(all_pages_blocks)

        # Passe 3 : extraire le texte page par page
        for page_data in all_pages_blocks:
            text = self._extract_page_text(
                page_data['blocks'],
                page_data['width'],
                page_data['height'],
                repetitive_lines
            )
            self.pages_data.append({
                'page_num': page_data['page_num'],
                'text': text,
                'height': page_data['height'],
                'width': page_data['width']
            })

        self.raw_text = "\n\n".join([p['text'] for p in self.pages_data if p['text'].strip()])
        print(f"  ✅ {len(self.raw_text)} caractères extraits sur {self.metadata['num_pages']} pages")

        return {
            'raw_text': self.raw_text,
            'metadata': self.metadata,
            'pages_data': self.pages_data
        }

    def _detect_repetitive_lines(self, all_pages_blocks: List[Dict]) -> set:
        """
        Détecte les lignes qui apparaissent sur au moins 30% des pages
        → ce sont de vrais headers/footers, pas du contenu.
        """
        n_pages = len(all_pages_blocks)
        if n_pages < 3:
            return set()  # Pas assez de pages pour détecter

        line_counter = Counter()
        for page_data in all_pages_blocks:
            page_lines = set()
            for b in page_data['blocks']:
                if b[6] == 0:  # bloc texte
                    for line in b[4].split('\n'):
                        clean = line.strip()
                        if clean and len(clean) > 2:
                            page_lines.add(clean)
            line_counter.update(page_lines)

        threshold = max(3, int(n_pages * 0.30))
        return {line for line, count in line_counter.items() if count >= threshold}

    def _detect_layout(self, blocks: list, page_width: float) -> str:
        """
        Détecte si la page est en mono-colonne ou multi-colonnes.
        Retourne 'single' ou 'multi'.
        """
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
        if len(text_blocks) < 4:
            return 'single'

        page_center = page_width / 2
        left_count = sum(1 for b in text_blocks if b[2] < page_center * 0.85)
        right_count = sum(1 for b in text_blocks if b[0] > page_center * 1.15)

        if left_count > 1 and right_count > 1:
            return 'multi'
        return 'single'

    def _extract_page_text(
        self,
        blocks: list,
        page_width: float,
        page_height: float,
        repetitive_lines: set
    ) -> str:
        """
        Extrait le texte d'une page en respectant le flux de lecture.
        - Multi-colonnes : lecture colonne gauche puis colonne droite
        - Mono-colonne : lecture de haut en bas
        """
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
        if not text_blocks:
            return ""

        layout = self._detect_layout(text_blocks, page_width)

        if layout == 'multi':
            page_center = page_width / 2
            left_blocks = [b for b in text_blocks if (b[0] + b[2]) / 2 < page_center]
            right_blocks = [b for b in text_blocks if (b[0] + b[2]) / 2 >= page_center]
            left_blocks.sort(key=lambda b: b[1])
            right_blocks.sort(key=lambda b: b[1])
            ordered_blocks = left_blocks + right_blocks
        else:
            ordered_blocks = sorted(text_blocks, key=lambda b: (b[1], b[0]))

        lines_out = []
        for b in ordered_blocks:
            for line in b[4].split('\n'):
                clean = line.strip()
                if not clean:
                    continue
                # Supprimer les lignes répétitives détectées automatiquement
                if clean in repetitive_lines:
                    continue
                # Supprimer les numéros de page isolés (ex: "42", " 7 ")
                if re.fullmatch(r'\d{1,4}', clean):
                    continue
                lines_out.append(clean)

        return '\n'.join(lines_out)


class XMLLoader:
    """
    Loader pour ordonnances et ordres XML.
    
    Gère:
    - Namespaces XML
    - Extraction sélective (métadonnées vs. contenu)
    - Transformation en texte enrichi
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.tree = None
        self.root = None
        self.namespaces = {}
    
    def load(self) -> Dict[str, Any]:
        """
        Parsing XML avec extraction métadonnées + contenu.
        """
        print(f"\n📋 Chargement XML: {self.file_path}")
        
        # Parsing
        self.tree = ET.parse(self.file_path)
        self.root = self.tree.getroot()
        
        # Détection des namespaces
        self._detect_namespaces()
        
        # Extraction métadonnées
        metadata = self._extract_metadata_from_xml()
        
        # Extraction contenu textuel
        content = self._extract_content_from_xml()
        
        print(f"  ✅ {len(content)} caractères extraits")
        
        return {
            'raw_text': content,
            'metadata': metadata,
            'source_type': 'xml',
            'source_file': os.path.basename(self.file_path)
        }
    
    def _detect_namespaces(self):
        """
        Détection automatique des namespaces XML.
        """
        # ElementTree parse automatiquement {namespace}tag
        # On extrait les namespaces depuis la racine
        if self.root.tag.startswith('{'):
            ns = self.root.tag[1:].split('}')[0]
            self.namespaces['default'] = ns
    
    def _extract_metadata_from_xml(self) -> Dict[str, Any]:
        """
        Extraction des métadonnées depuis les balises XML.
        """
        metadata = {
            'source_file': os.path.basename(self.file_path),
            'source_type': 'xml'
        }
        
        # Liste des balises métadonnées communes
        metadata_tags = [
            'reference', 'Reference', 'REFERENCE',
            'juridiction', 'Juridiction', 'JURIDICTION',
            'date', 'Date', 'DATE',
            'numero', 'Numero', 'NUMERO',
            'type', 'Type', 'TYPE',
            'formation', 'Formation',
            'president', 'President',
            'dispositif', 'Dispositif'
        ]
        
        # Recherche dans tout l'arbre
        for tag in metadata_tags:
            # Recherche sans namespace
            elem = self.root.find(f".//{tag}")
            if elem is not None and elem.text:
                # On normalise le nom de la clé en lowercase
                key = tag.lower()
                metadata[key] = elem.text.strip()
        
        # Extraction des attributs de la racine (souvent informatifs)
        if self.root.attrib:
            for key, value in self.root.attrib.items():
                # On préfixe les attributs pour les distinguer
                metadata[f"attr_{key}"] = value
        
        return metadata
    
    def _extract_content_from_xml(self) -> str:
        """
        Extraction du contenu textuel pertinent.
        """
        content_parts = []
        
        def traverse(element, depth=0):
            """Parcours récursif avec enrichissement."""
            # On skip les balises "metadata" connues
            skip_tags = ['reference', 'juridiction', 'date', 'numero']
            
            tag_name = element.tag.split('}')[-1].lower()  # Enlève namespace
            
            # Si c'est une balise de contenu avec du texte
            if element.text and element.text.strip() and tag_name not in skip_tags:
                # On enrichit avec le nom de la balise (contexte)
                text = element.text.strip()
                
                # Si la balise a un nom sémantique, on l'ajoute
                if tag_name not in ['p', 'div', 'span']:
                    content_parts.append(f"[{tag_name}]: {text}")
                else:
                    content_parts.append(text)
            
            # Récursion sur les enfants
            for child in element:
                traverse(child, depth + 1)
        
        traverse(self.root)
        
        return "\n".join(content_parts)


class JSONLoader:
    """
    Loader pour métadonnées JSON.
    
    Transformation intelligente clé-valeur → texte naturel.
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.data = None
    
    def load(self) -> Dict[str, Any]:
        """
        Chargement et transformation JSON.
        """
        print(f"\n📊 Chargement JSON: {self.file_path}")
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        # Séparation métadonnées / contenu
        metadata, content_text = self._transform_json(self.data)
        
        metadata['source_file'] = os.path.basename(self.file_path)
        metadata['source_type'] = 'json'
        
        print(f"  ✅ {len(content_text)} caractères générés")
        
        return {
            'raw_text': content_text,
            'metadata': metadata
        }
    
    def _transform_json(self, data: Dict, prefix="") -> Tuple[Dict, str]:
        """
        Transformation récursive JSON → (métadonnées, texte).
        """
        metadata = {}
        content_parts = []
        
        for key, value in data.items():
            full_key = f"{prefix}{key}" if prefix else key
            
            # 1. Types numériques/booléens → Métadonnées
            if isinstance(value, (int, float, bool)):
                metadata[full_key] = value
            
            # 2. Chaînes de caractères → Analyse
            elif isinstance(value, str):
                # Est-ce une date ISO ?
                if self._is_iso_date(value):
                    metadata[full_key] = value
                    # On l'ajoute aussi au contenu pour recherche sémantique
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {self._format_date(value)}"
                    )
                
                # Est-ce un identifiant/code ?
                elif self._is_structured_field(key, value):
                    metadata[full_key] = value
                
                # Sinon, c'est du contenu textuel
                else:
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {value}"
                    )
                    # On garde aussi une version shortened en métadonnée si pertinent
                    if len(value) < 100:
                        metadata[f"{full_key}_short"] = value[:100]
            
            # 3. Listes → Énumération
            elif isinstance(value, list):
                if value:
                    # On compte les éléments (métadonnée)
                    metadata[f"{full_key}_count"] = len(value)
                    
                    # On énumère les éléments (contenu)
                    items_str = ", ".join([str(v) for v in value])
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {items_str}"
                    )
            
            # 4. Objets imbriqués → Récursion
            elif isinstance(value, dict):
                nested_meta, nested_text = self._transform_json(value, f"{full_key}.")
                metadata.update(nested_meta)
                if nested_text:
                    content_parts.append(
                        f"\n{key.replace('_', ' ').title()}:\n{nested_text}"
                    )
        
        content_text = "\n".join(content_parts)
        return metadata, content_text
    
    @staticmethod
    def _is_iso_date(value: str) -> bool:
        """Détection date ISO."""
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return True
        except:
            return False
    
    @staticmethod
    def _format_date(iso_date: str) -> str:
        """Formatage date pour texte naturel."""
        try:
            dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
            # Format français: 4 novembre 2025
            mois_fr = [
                '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
            ]
            return f"{dt.day} {mois_fr[dt.month]} {dt.year}"
        except:
            return iso_date
    
    @staticmethod
    def _is_structured_field(key: str, value: str) -> bool:
        """Heuristique pour détecter champs structurés."""
        # Clés contenant ces mots = structuré
        if any(k in key.lower() for k in ['id', 'code', 'ref', 'numero', 'num']):
            return True
        
        # Valeur courte sans espaces = structuré
        if len(value) < 50 and ' ' not in value:
            return True
        
        return False
