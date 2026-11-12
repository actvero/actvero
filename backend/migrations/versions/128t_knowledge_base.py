"""Add versioned knowledge sources, parser credentials and index jobs."""

from alembic import op

revision = "128t_knowledge_base"
down_revision = "127s_departments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE knowledge_settings (
	tenant_id UUID NOT NULL,
	version INTEGER NOT NULL,
	embedding_model_id UUID,
	rerank_model_id UUID,
	rerank_enabled BOOLEAN NOT NULL,
	executor_member_id UUID,
	authorized_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (tenant_id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id),
	FOREIGN KEY(embedding_model_id) REFERENCES llm_models (id),
	FOREIGN KEY(rerank_model_id) REFERENCES llm_models (id),
	FOREIGN KEY(executor_member_id) REFERENCES memberships (id)
)
    """)
    op.execute("""
CREATE TABLE knowledge_parser_credentials (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	name VARCHAR(100) NOT NULL,
	account VARCHAR(100) NOT NULL,
	secret TEXT NOT NULL,
	enabled BOOLEAN NOT NULL,
	cooldown_until TIMESTAMP WITH TIME ZONE,
	last_used_at TIMESTAMP WITH TIME ZONE,
	error VARCHAR(300) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
)
    """)
    op.execute(
        "CREATE INDEX ix_knowledge_parser_credentials_tenant_id "
        "ON knowledge_parser_credentials (tenant_id)"
    )
    op.execute("""
CREATE TABLE knowledge_bases (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	name VARCHAR(100) NOT NULL,
	archived BOOLEAN NOT NULL,
	description VARCHAR(1000) NOT NULL,
	audience VARCHAR(20) NOT NULL,
	member_ids JSONB NOT NULL,
	department_grants JSONB NOT NULL,
	chunking JSONB NOT NULL,
	embedding_profile JSONB NOT NULL,
	version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
)
    """)
    op.execute("CREATE INDEX ix_knowledge_bases_tenant_id ON knowledge_bases (tenant_id)")
    op.execute("""
CREATE TABLE knowledge_documents (
	id UUID NOT NULL,
	base_id UUID NOT NULL,
	upload_id UUID NOT NULL,
	filename VARCHAR(200) NOT NULL,
	media_type VARCHAR(100) NOT NULL,
	size INTEGER NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	data BYTEA NOT NULL,
	active_generation_id UUID,
	latest_generation_id UUID,
	deleted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (base_id, upload_id),
	FOREIGN KEY(base_id) REFERENCES knowledge_bases (id)
)
    """)
    op.execute("CREATE INDEX ix_knowledge_documents_base_id ON knowledge_documents (base_id)")
    op.execute("""
CREATE TABLE knowledge_generations (
	id UUID NOT NULL,
	document_id UUID NOT NULL,
	actor_member_id UUID NOT NULL,
	chunking JSONB NOT NULL,
	embedding_profile JSONB NOT NULL,
	status VARCHAR(30) NOT NULL,
	error VARCHAR(500) NOT NULL,
	raw_parse JSONB NOT NULL,
	blocks JSONB NOT NULL,
	batch_id VARCHAR(100),
	credential_id UUID,
	upload_url TEXT,
	submission_pending BOOLEAN NOT NULL,
	inference_pending BOOLEAN NOT NULL,
	next_run_at TIMESTAMP WITH TIME ZONE NOT NULL,
	lease_token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id),
	FOREIGN KEY(actor_member_id) REFERENCES memberships (id),
	FOREIGN KEY(credential_id) REFERENCES knowledge_parser_credentials (id)
)
    """)
    op.execute(
        "CREATE INDEX ix_knowledge_generations_document_id ON knowledge_generations (document_id)"
    )
    op.execute("CREATE INDEX ix_knowledge_generations_status ON knowledge_generations (status)")
    op.execute("""
CREATE TABLE knowledge_chunks (
	id UUID NOT NULL,
	generation_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	content TEXT NOT NULL,
	sources JSONB NOT NULL,
	vector JSONB,
	PRIMARY KEY (id),
	UNIQUE (generation_id, sequence),
	FOREIGN KEY(generation_id) REFERENCES knowledge_generations (id)
)
    """)
    op.execute("CREATE INDEX ix_knowledge_chunks_generation_id ON knowledge_chunks (generation_id)")


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_generations")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
    op.drop_table("knowledge_parser_credentials")
    op.drop_table("knowledge_settings")
