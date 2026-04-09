
from ragas.metrics import context_precision, answer_relevancy, faithfulness
from ragas import evaluate
from datasets import Dataset

def evaluate_rag(question, answer, context):
    """
    Évalue un RAG à l'aide de Ragas.
    - questions : liste de chaînes
    - answers : réponses générées par ton modèle RAG
    - contexts : liste de listes de passages récupérés
    """

    # un dataset 
    data = {
    "question": [question],
    "answer": [answer],
    "contexts": [[context]],
    "reference": [answer]  # ou la vraie réponse de référence
}


    ds = Dataset.from_dict(data)

    # Choix des métriques (les 3 plus importantes)
    metrics=[faithfulness, answer_relevancy, context_precision]


    # Évaluation
    results = evaluate(ds, metrics=metrics)

    return results
