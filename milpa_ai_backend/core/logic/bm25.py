# milpa_ai_backend/core/logic/bm25.py
# ------------------------------------------------------------
# Búsqueda léxica (BM25) priorizando Tantivy (python-tantivy),
# con fallback a Whoosh y, en último caso, a un BM25/TF-IDF en
# memoria. Este módulo corrige la compatibilidad con versiones
# de python-tantivy donde Document.add_text espera NOMBRES de
# campo (str) y no objetos Field.
#
# API pública compatible con pruebas:
#   - idx = BM25Index(index_dir="...", backend=None)
#   - idx.reset()
#   - idx.index_many(docs_ml)   # docs_ml = [{fragment_id,text/text_es,labels[],doc_id,entities[]}, ...]
#   - idx.add_documents(docs)   # docs    = [{id,text,metadata{doc_id,labels,entities}}, ...]
#   - idx.add(id, text, metadata=None)
#   - idx.index(docs)           # alias de add_documents
#   - idx.search(query, topk=100, labels_filter=None)
#
# Selección de backend:
#  - Si existe 'tantivy' -> usa tantivy salvo que BM25_BACKEND=whoosh|memory
#  - Si no hay tantivy y sí whoosh -> usa whoosh
#  - Si no hay ninguno -> memoria
#
# Notas clave:
#  - **Tantivy**: se añaden campos con add_text("nombre_de_campo", valor),
#    NUNCA con objetos Field. Esto evita TypeError en versiones donde
#    add_text requiere str.
#  - **Whoosh**: requiere paquete 'whoosh'. Si falta, cae a memoria.
#  - **Memoria**: implementación BM25 básica, suficiente para tests.
# ------------------------------------------------------------
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import os
import shutil
import re
import math
from dataclasses import dataclass
from collections import Counter, defaultdict

# ---------- Detección de backends disponibles ----------
# Tantivy (python-tantivy moderno)
try:
    import tantivy  # type: ignore
except Exception:
    tantivy = None  # noqa: N816

# Whoosh
try:
    from whoosh import index as whoosh_index  # type: ignore
    from whoosh.fields import Schema as WhooshSchema, TEXT as W_TEXT, ID as W_ID, KEYWORD as W_KEYWORD  # type: ignore
    from whoosh.qparser import MultifieldParser as WhooshMultifieldParser  # type: ignore
except Exception:
    whoosh_index = None
    WhooshSchema = None  # type: ignore
    W_TEXT = None  # type: ignore
    W_ID = None  # type: ignore
    W_KEYWORD = None  # type: ignore
    WhooshMultifieldParser = None  # type: ignore


@dataclass
class _DocLite:
    fragment_id: str
    text: str
    labels: List[str]
    doc_id: str
    entities: List[Dict[str, str]]


class BM25Index:
    """
    Índice BM25 con tres posibles backends:
      - 'tantivy'  (si python-tantivy está presente y es compatible)
      - 'whoosh'   (si whoosh está presente)
      - 'memory'   (si no hay nada más; BM25 básico)

    Se puede forzar con la variable de entorno BM25_BACKEND=tantivy|whoosh|memory
    """

    # Marker de versión del esquema Tantivy. Bumpear cuando se cambien analyzers
    # o el conjunto de campos para forzar reset automático del índice persistido.
    SCHEMA_VERSION = "ml_es_v1"
    _ANALYZER_NAMES = {
        "text": "ml_es",
        "labels": "raw",
        "fragment_id": "raw",
        "doc_id": "raw",
    }

    def __init__(self, index_dir: str = "data/bm25_index", backend: Optional[str] = None):
        self.index_dir = index_dir
        os.makedirs(index_dir, exist_ok=True)

        forced = (backend or os.environ.get("BM25_BACKEND", "")).strip().lower()
        self.backend = "memory"  # valor por defecto seguro
        self._mem_docs: Dict[str, _DocLite] = {}
        self._mem_df: Dict[str, int] = defaultdict(int)
        self._mem_N = 0

        # ---------- Tantivy ----------
        self._tv_index = None
        self._tv_schema = None
        # Usamos SIEMPRE nombres de campos (str) para add_text:
        self._tv_field_names = {
            "fragment_id": "fragment_id",
            "text": "text",
            "labels": "labels",
            "doc_id": "doc_id",
        }

        # ---------- Whoosh ----------
        self._wh_index = None
        self._wh_schema = None

        # Selección de backend (con detección y fallback)
        if forced in {"tantivy", "whoosh", "memory"}:
            if forced == "tantivy" and self._try_init_tantivy():
                self.backend = "tantivy"
            elif forced == "whoosh" and self._try_init_whoosh():
                self.backend = "whoosh"
            else:
                self.backend = "memory"
        else:
            if self._try_init_tantivy():
                self.backend = "tantivy"
            elif self._try_init_whoosh():
                self.backend = "whoosh"
            else:
                self.backend = "memory"

    # ------------------------- Tantivy -------------------------

    # ------------------------- Analyzers multilingües -------------------------

    def _build_multilingual_analyzers(self) -> Dict[str, Any]:
        """Construye analyzers Tantivy para campos textuales.

        Los analyzers que retornamos están pensados para Tantivy 0.26+ (clase
        ``TextAnalyzerBuilder`` + ``Filter``). En versiones más antiguas de
        python-tantivy estas clases no existen y el método retorna un dict
        vacío; el índice usará el analyzer por defecto.

        Cadenas configuradas:
          - ``ml_es``: simple → lowercase → ascii_fold → stemmer(spanish).
            Da match entre ``maíz``/``maiz``, ``café``/``cafe`` y aplica
            stemming castellano para que ``calabazas`` matchee ``calabaza``.
          - ``ml_en``: equivalente para inglés (stemmer english) — útil para
            documentos técnicos mezclados.
        """
        if not all(
            hasattr(tantivy, x)
            for x in ("TextAnalyzerBuilder", "Tokenizer", "Filter")
        ):
            return {}
        analyzers: Dict[str, Any] = {}
        try:
            es = (
                tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
                .filter(tantivy.Filter.lowercase())
                .filter(tantivy.Filter.ascii_fold())
                .filter(tantivy.Filter.stemmer("spanish"))
                .build()
            )
            analyzers["ml_es"] = es
        except Exception:
            pass
        try:
            en = (
                tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
                .filter(tantivy.Filter.lowercase())
                .filter(tantivy.Filter.ascii_fold())
                .filter(tantivy.Filter.stemmer("english"))
                .build()
            )
            analyzers["ml_en"] = en
        except Exception:
            pass
        return analyzers

    def _schema_marker_path(self) -> str:
        return os.path.join(self.index_dir, ".schema_version")

    def _read_schema_marker(self) -> Optional[str]:
        p = self._schema_marker_path()
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read().strip() or None
        except Exception:
            return None
        return None

    def _write_schema_marker(self) -> None:
        try:
            with open(self._schema_marker_path(), "w", encoding="utf-8") as f:
                f.write(self.SCHEMA_VERSION)
        except Exception:
            pass

    def _try_init_tantivy(self) -> bool:
        """
        Devuelve True si Tantivy está disponible y se pudo crear/abrir el índice
        con la API moderna (SchemaBuilder, QueryParser, etc.).

        Si el índice persistido tiene un schema version distinto al actual,
        se recrea limpio antes de reabrirlo. Esto cubre el caso de migrar a
        un analyzer multilingüe sin requerir intervención manual.
        """
        if tantivy is None:
            return False
        if not hasattr(tantivy, "SchemaBuilder"):
            return False

        try:
            analyzers = self._build_multilingual_analyzers()
            tk_text = self._ANALYZER_NAMES["text"] if "ml_es" in analyzers else "default"
            tk_raw = "raw"

            sb = tantivy.SchemaBuilder()
            try:
                sb.add_text_field(
                    self._tv_field_names["fragment_id"],
                    stored=True,
                    tokenizer_name=tk_raw,
                )
                sb.add_text_field(
                    self._tv_field_names["text"],
                    stored=False,
                    tokenizer_name=tk_text,
                )
                sb.add_text_field(
                    self._tv_field_names["labels"],
                    stored=True,
                    tokenizer_name=tk_raw,
                )
                sb.add_text_field(
                    self._tv_field_names["doc_id"],
                    stored=True,
                    tokenizer_name=tk_raw,
                )
            except TypeError:
                # python-tantivy más antiguo: tokenizer_name no soportado.
                analyzers = {}
                sb = tantivy.SchemaBuilder()
                sb.add_text_field(self._tv_field_names["fragment_id"], stored=True)
                sb.add_text_field(self._tv_field_names["text"], stored=False)
                sb.add_text_field(self._tv_field_names["labels"], stored=True)
                sb.add_text_field(self._tv_field_names["doc_id"], stored=True)

            schema = sb.build()

            existing_marker = self._read_schema_marker()
            schema_changed = existing_marker != self.SCHEMA_VERSION
            has_files = os.path.isdir(self.index_dir) and any(
                f for f in os.listdir(self.index_dir)
                if not f.startswith(".schema")
            )

            if schema_changed and has_files:
                # Reset automático: el schema cambió respecto al persistido.
                shutil.rmtree(self.index_dir, ignore_errors=True)
                os.makedirs(self.index_dir, exist_ok=True)
                has_files = False

            # Crear o abrir índice
            if not has_files:
                index = tantivy.Index(schema, path=self.index_dir)
            else:
                try:
                    index = tantivy.Index(schema, path=self.index_dir, reuse=True)
                except Exception:
                    # Como último recurso, reset.
                    shutil.rmtree(self.index_dir, ignore_errors=True)
                    os.makedirs(self.index_dir, exist_ok=True)
                    index = tantivy.Index(schema, path=self.index_dir)

            for name, analyzer in analyzers.items():
                try:
                    index.register_tokenizer(name, analyzer)
                except Exception:
                    pass

            self._tv_schema = schema
            self._tv_index = index
            self._write_schema_marker()
            return True
        except Exception:
            self._tv_schema = None
            self._tv_index = None
            return False

    def _tv_build_query(self, query: str):
        """
        Construye una query para Tantivy, normalizando NFC y usando un query
        parser tolerante (no rompe ante caracteres especiales del query
        language como ``:`` o paréntesis sueltos).
        """
        if self._tv_index is None or self._tv_schema is None:
            return None
        from milpa_ai_backend.core.logic.text_norm import normalize_unicode
        q_norm = normalize_unicode(query)
        if not q_norm:
            return None
        fields = [self._tv_field_names["text"], self._tv_field_names["labels"]]

        # Intento 1: parse_query_lenient (tolerante a sintaxis rara)
        try:
            lenient = getattr(self._tv_index, "parse_query_lenient", None)
            if callable(lenient):
                parsed = lenient(q_norm, fields)
                # parse_query_lenient retorna (query, errors) en algunas versiones
                if isinstance(parsed, tuple) and parsed:
                    return parsed[0]
                return parsed
        except Exception:
            pass

        # Intento 2: parse_query estándar
        try:
            parse_query = getattr(self._tv_index, "parse_query", None)
            if callable(parse_query):
                return parse_query(q_norm, fields)
        except Exception:
            pass

        # Intento 3: QueryParser legacy
        try:
            if hasattr(tantivy, "QueryParser"):
                qp = tantivy.QueryParser(self._tv_schema, fields)
                return qp.parse_query(q_norm)
        except Exception:
            pass
        return None

    # ------------------------- Whoosh --------------------------

    def _build_whoosh_analyzer(self):
        """Analyzer Whoosh multilingüe: tokeniza, baja a minúsculas, hace
        folding ASCII y stemming en español. Si el módulo de stemming no está
        disponible (instalación parcial), cae a un StandardAnalyzer simple.
        """
        try:
            from whoosh.analysis import (
                RegexTokenizer,
                LowercaseFilter,
                StopFilter,
                StemFilter,
            )
            try:
                from whoosh.analysis.filters import CharsetFilter
                from whoosh.support.charset import accent_map
                fold_filter = CharsetFilter(accent_map)
            except Exception:
                fold_filter = None

            try:
                from whoosh.lang.snowball.spanish import SpanishStemmer
                stem_fn = SpanishStemmer().stem
            except Exception:
                stem_fn = None

            tokenizer = RegexTokenizer(expression=r"[\w]+", gaps=False)
            chain = tokenizer | LowercaseFilter()
            if fold_filter is not None:
                chain = chain | fold_filter
            chain = chain | StopFilter(minsize=2)
            if stem_fn is not None:
                chain = chain | StemFilter(stemfn=stem_fn)
            return chain
        except Exception:
            return None

    def _try_init_whoosh(self) -> bool:
        """
        Devuelve True si Whoosh está disponible y se pudo crear/abrir el índice.

        Configura un analyzer multilingüe (lowercase + folding ASCII + stemming
        español) sobre el campo ``text`` para que las queries con/sin acentos y
        con flexiones morfológicas comunes recuperen los mismos documentos.
        """
        if whoosh_index is None or WhooshSchema is None:
            return False
        try:
            from whoosh.fields import TEXT as W_TEXT_FULL  # type: ignore
            ml_analyzer = self._build_whoosh_analyzer()
            schema_kwargs = {
                "fragment_id": W_ID(stored=True, unique=True),
                "labels": W_KEYWORD(stored=True, commas=True, lowercase=True),
                "doc_id": W_ID(stored=True),
            }
            if ml_analyzer is not None:
                schema_kwargs["text"] = W_TEXT_FULL(stored=True, analyzer=ml_analyzer)
            else:
                schema_kwargs["text"] = W_TEXT(stored=True)

            schema = WhooshSchema(**schema_kwargs)
            # Si ya existe un índice persistido pero su schema no coincide,
            # Whoosh fallará al indexar. Nos protegemos haciendo reset cuando
            # el marker no coincide.
            existing = self._read_schema_marker()
            wh_marker = f"whoosh::{self.SCHEMA_VERSION}"
            if existing and existing != wh_marker and whoosh_index.exists_in(self.index_dir):
                shutil.rmtree(self.index_dir, ignore_errors=True)
                os.makedirs(self.index_dir, exist_ok=True)
            if not whoosh_index.exists_in(self.index_dir):
                whoosh_index.create_in(self.index_dir, schema)
            idx = whoosh_index.open_dir(self.index_dir)
            self._wh_schema = schema
            self._wh_index = idx
            try:
                with open(self._schema_marker_path(), "w", encoding="utf-8") as f:
                    f.write(wh_marker)
            except Exception:
                pass
            return True
        except Exception:
            self._wh_schema = None
            self._wh_index = None
            return False

    # ------------------------ Utilidades -----------------------

    def reset(self) -> None:
        """
        Elimina y recrea el índice del backend seleccionado.
        """
        if self.backend == "tantivy":
            if os.path.exists(self.index_dir):
                shutil.rmtree(self.index_dir, ignore_errors=True)
            os.makedirs(self.index_dir, exist_ok=True)
            self._try_init_tantivy()

        elif self.backend == "whoosh":
            if os.path.exists(self.index_dir):
                shutil.rmtree(self.index_dir, ignore_errors=True)
            os.makedirs(self.index_dir, exist_ok=True)
            self._try_init_whoosh()

        else:
            self._mem_docs.clear()
            self._mem_df.clear()
            self._mem_N = 0

    def delete_by_doc_id(self, doc_id: str) -> int:
        """Elimina todos los fragmentos asociados a un doc_id del índice activo.

        Devuelve el número de documentos eliminados (best-effort). Esto evita
        fragmentos huérfanos cuando se re-ingestan documentos cuyo SHA-256
        coincide con el anterior pero cuyos UUID de fragmento son nuevos.
        """
        if not doc_id:
            return 0
        deleted = 0
        if self.backend == "tantivy":
            if self._tv_index is None and not self._try_init_tantivy():
                return 0
            try:
                writer = self._tv_index.writer()
                term_field = self._tv_field_names["doc_id"]
                fn = getattr(writer, "delete_documents", None)
                if callable(fn):
                    try:
                        fn(term_field, doc_id)
                    except TypeError:
                        try:
                            fn(field_name=term_field, field_value=doc_id)
                        except Exception:
                            pass
                writer.commit()
                try:
                    self._tv_index.reload()
                except Exception:
                    pass
                deleted = 1
            except Exception:
                deleted = 0
            return deleted
        if self.backend == "whoosh":
            if self._wh_index is None and not self._try_init_whoosh():
                return 0
            try:
                writer = self._wh_index.writer()
                deleted = writer.delete_by_term("doc_id", doc_id)
                writer.commit()
            except Exception:
                deleted = 0
            return deleted
        before = len(self._mem_docs)
        self._mem_docs = [
            d for d in self._mem_docs if (d.get("metadata") or {}).get("doc_id") != doc_id
        ]
        deleted = before - len(self._mem_docs)
        return deleted

    # ------------------- API de indexación (tests) -------------------

    def add_documents(self, docs: List[Dict[str, Any]]) -> None:
        """
        API esperada por los tests:
          docs = [{ "id": str, "text": str, "metadata": { "doc_id": str, "labels": [..], "entities":[..] } }, ...]
        """
        ml_docs: List[Dict[str, Any]] = []
        for d in docs:
            rid = d.get("id", "")
            text = d.get("text", "") or ""
            md = d.get("metadata", {}) or {}
            labels = md.get("labels", []) or []
            if isinstance(labels, str):
                # permitir 'a,b,c' o 'a b c'
                labels = [x for x in re.split(r"[,\s]+", labels) if x]
            ml_docs.append({
                "fragment_id": rid,
                "text": text,
                "labels": labels,
                "doc_id": md.get("doc_id", ""),
                "entities": md.get("entities", []) or [],
            })
        self.index_many(ml_docs)

    def add(self, rid: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        API uno-a-uno esperada por los tests.
        """
        md = metadata or {}
        labels = md.get("labels", []) or []
        if isinstance(labels, str):
            labels = [x for x in re.split(r"[,\s]+", labels) if x]
        self.index_many([{
            "fragment_id": rid,
            "text": text or "",
            "labels": labels,
            "doc_id": md.get("doc_id", ""),
            "entities": md.get("entities", []) or [],
        }])

    def index(self, docs: List[Dict[str, Any]]) -> None:
        """
        Alias de add_documents(docs) por compatibilidad.
        """
        self.add_documents(docs)

    # --------------------- Indexación (motor) --------------------

    def index_many(self, docs: List[Dict[str, Any]]) -> None:
        """
        Indexa una lista de documentos en el backend activo:
          docs_ml = [
            {
              "fragment_id": str,
              "text_es" | "text": str,
              "labels": [str, ...],
              "doc_id": str,
              "entities": [{...}]   # opcional
            }, ...
          ]
        """
        from milpa_ai_backend.core.logic.text_norm import normalize_unicode

        if self.backend == "tantivy":
            if self._tv_index is None and not self._try_init_tantivy():
                self._index_many_memory(docs)
                return

            writer = self._tv_index.writer()

            # Construimos tantivy.Document manualmente (add_text con NOMBRE de campo)
            for d in docs:
                textval = normalize_unicode(d.get("text_es") or d.get("text") or "")
                labels_joined = " ".join(d.get("labels", []))
                tdoc = tantivy.Document()
                # IMPORTANTE: usar SIEMPRE nombres de campo (str), NO objetos Field
                tdoc.add_text(self._tv_field_names["fragment_id"], d.get("fragment_id", ""))
                tdoc.add_text(self._tv_field_names["text"], textval)
                tdoc.add_text(self._tv_field_names["labels"], labels_joined)
                tdoc.add_text(self._tv_field_names["doc_id"], d.get("doc_id", ""))
                writer.add_document(tdoc)
            writer.commit()
            try:
                self._tv_index.reload()
            except Exception:
                pass
            return

        if self.backend == "whoosh":
            if self._wh_index is None and not self._try_init_whoosh():
                self._index_many_memory(docs)
                return

            writer = self._wh_index.writer()
            for d in docs:
                writer.update_document(
                    fragment_id=d.get("fragment_id", ""),
                    text=normalize_unicode(d.get("text_es") or d.get("text") or ""),
                    labels=",".join(d.get("labels", [])),
                    doc_id=d.get("doc_id", ""),
                )
            writer.commit()
            return

        # memoria
        self._index_many_memory(docs)

    def _index_many_memory(self, docs: List[Dict[str, Any]]) -> None:
        from milpa_ai_backend.core.logic.text_norm import (
            fold_ascii_lower,
            simple_tokens,
        )

        for d in docs:
            fid = d["fragment_id"]
            raw_text = (d.get("text_es") or d.get("text") or "")
            folded = fold_ascii_lower(raw_text)
            toks = simple_tokens(folded)
            self._mem_docs[fid] = _DocLite(
                fragment_id=fid,
                text=folded,
                labels=d.get("labels", []),
                doc_id=d.get("doc_id", ""),
                entities=d.get("entities", []),
            )
            for w in set(toks):
                self._mem_df[w] += 1
        self._mem_N = len(self._mem_docs)

    # ------------------------ Búsqueda -------------------------

    def search(
        self,
        query: str,
        topk: int = 100,
        labels_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retorna una lista de hits con estructura:
          [
            {
              "fragment_id": str,
              "score": float,
              "metadata": {
                "doc_id": str,
                "labels": [str, ...],
                "entities": [...]
              }
            },
            ...
          ]
        """
        if self.backend == "tantivy":
            return self._search_tantivy(query, topk, labels_filter)

        if self.backend == "whoosh":
            return self._search_whoosh(query, topk, labels_filter)

        return self._search_memory(query, topk, labels_filter)

    # ---- Tantivy ----

    def _search_tantivy(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        if self._tv_index is None and not self._try_init_tantivy():
            return []

        # Construir query compatible
        q = self._tv_build_query(query)
        if q is None:
            return []

        searcher = self._tv_index.searcher()
        try:
            top_docs = searcher.search(q, topk)
        except Exception:
            return []

        # Compatibilidad: algunas versiones exponen .hits; en otras es lista de tuplas
        hits_iter: List[Tuple[float, Any]]
        if hasattr(top_docs, "hits"):
            hits_iter = top_docs.hits  # type: ignore[assignment]
        else:
            hits_iter = top_docs  # type: ignore[assignment]

        out: List[Dict[str, Any]] = []
        for score, doc_addr in hits_iter:
            doc = searcher.doc(doc_addr)

            # fragment_id - compatibilidad tantivy-py: usar indexing en lugar de .get()
            try:
                f_id_val = doc[self._tv_field_names["fragment_id"]]
            except (KeyError, TypeError):
                # Fallback si doc es dict o tiene .get()
                f_id_val = doc.get(self._tv_field_names["fragment_id"]) if hasattr(doc, "get") else ""
            fragment_id = f_id_val[0] if isinstance(f_id_val, list) else (f_id_val or "")

            # doc_id
            try:
                d_id_val = doc[self._tv_field_names["doc_id"]]
            except (KeyError, TypeError):
                d_id_val = doc.get(self._tv_field_names["doc_id"]) if hasattr(doc, "get") else ""
            doc_id = d_id_val[0] if isinstance(d_id_val, list) else (d_id_val or "")

            # labels
            try:
                lbl = doc[self._tv_field_names["labels"]]
            except (KeyError, TypeError):
                lbl = doc.get(self._tv_field_names["labels"]) if hasattr(doc, "get") else ""
            raw_labels = lbl[0] if isinstance(lbl, list) else (lbl or "")
            labels = [l for l in str(raw_labels).split() if l]

            if labels_filter and not any(l in labels for l in labels_filter):
                continue

            out.append({
                "fragment_id": fragment_id,
                "score": float(score),
                "metadata": {
                    "doc_id": doc_id,
                    "labels": labels,
                    "entities": [],  # no almacenamos entidades en BM25
                }
            })
        return out

    # ---- Whoosh ----

    def _search_whoosh(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        if self._wh_index is None and not self._try_init_whoosh():
            return []

        from milpa_ai_backend.core.logic.text_norm import normalize_unicode
        q_norm = normalize_unicode(query)

        with self._wh_index.searcher() as s:
            parser = WhooshMultifieldParser(["text", "labels"], schema=self._wh_index.schema)
            try:
                q = parser.parse(q_norm)
            except Exception:
                # Si la sintaxis incluye caracteres especiales, parsea modo plano.
                q = parser.parse(re.sub(r"[^\w\s]+", " ", q_norm))
            hits = s.search(q, limit=topk)
            out: List[Dict[str, Any]] = []
            for h in hits:
                labels = (h.get("labels") or "").split(",")
                if labels_filter and not any(l in labels for l in labels_filter):
                    continue
                out.append({
                    "fragment_id": h["fragment_id"],
                    "score": float(h.score),
                    "metadata": {
                        "doc_id": h.get("doc_id"),
                        "labels": labels,
                        "entities": [],
                    }
                })
            return out

    # ---- Memoria ----

    def _search_memory(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        from milpa_ai_backend.core.logic.text_norm import (
            fold_ascii_lower,
            simple_tokens,
        )

        q_tokens = simple_tokens(fold_ascii_lower(query))
        if not q_tokens:
            return []

        scores: List[Tuple[str, float, _DocLite]] = []
        k1 = 1.5
        b = 0.75

        doc_lens: Dict[str, int] = {}
        avgdl = 0.0
        for fid, d in self._mem_docs.items():
            toks = simple_tokens(d.text)
            doc_lens[fid] = len(toks)
            avgdl += len(toks)
        avgdl = (avgdl / max(len(self._mem_docs), 1)) if self._mem_docs else 0.0

        for fid, d in self._mem_docs.items():
            if labels_filter and not any(l in d.labels for l in labels_filter):
                continue
            toks = simple_tokens(d.text)
            tf = Counter(toks)
            score = 0.0
            for w in q_tokens:
                df = self._mem_df.get(w, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (self._mem_N - df + 0.5) / (df + 0.5))
                denom = tf[w] + k1 * (1 - b + b * (doc_lens[fid] / max(avgdl, 1.0)))
                score += idf * (tf[w] * (k1 + 1)) / max(denom, 1e-9)
            if score > 0:
                scores.append((fid, score, d))

        scores.sort(key=lambda x: x[1], reverse=True)
        out: List[Dict[str, Any]] = []
        for fid, sc, d in scores[:topk]:
            out.append({
                "fragment_id": fid,
                "score": float(sc),
                "metadata": {
                    "doc_id": d.doc_id,
                    "labels": d.labels,
                    "entities": d.entities
                }
            })
        return out
