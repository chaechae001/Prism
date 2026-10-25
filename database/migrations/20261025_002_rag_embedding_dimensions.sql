-- Keep E5 and local BGE caches separate by model_id while permitting both dimensions.
alter table private.prism_rag_chunks drop constraint prism_rag_chunks_embedding_check;
alter table private.prism_rag_chunks add constraint prism_rag_chunks_embedding_check
  check (cardinality(embedding) in (384,1024));
