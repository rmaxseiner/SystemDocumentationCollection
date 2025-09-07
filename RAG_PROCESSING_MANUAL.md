# RAG Data Extraction Pipeline Manual

## Overview

The RAG (Retrieval-Augmented Generation) Data Extraction Pipeline transforms raw infrastructure data collected from various systems into structured, queryable data suitable for conversational infrastructure management. This system enables natural language investigation workflows through semantically tagged, relationship-rich data.

## Architecture

```
Collectors → RAG Processors → Queryable Data
     ↓              ↓              ↓
  Raw Data    Structured     Conversational
              Metadata         Interface
```

### Pipeline Flow
1. **Collection Phase**: Gather raw data from infrastructure systems (existing)
2. **RAG Processing Phase**: Transform data through 4-step extraction pipeline (new)
3. **Query Phase**: Use processed data for conversational infrastructure management (future)

## Installation & Setup

### Prerequisites
- Python 3.8+
- Existing infrastructure collection system
- Optional: OpenAI API key for enhanced semantic tagging

### Dependencies
The RAG processing system uses existing dependencies plus:
- `openai` (optional, for API-based LLM)
- `pyyaml` (existing)
- `pathlib` (built-in)

### Quick Start
```bash
# Test the RAG processing pipeline
python3 test_rag_processor.py

# Run full pipeline with RAG processing
python3 infrastructure_pipeline.py full-pipeline

# Run only RAG processing on existing data
python3 infrastructure_pipeline.py process
```

## Configuration

### RAG Processing Configuration

Add the following section to your `config/systems.yml` file:

```yaml
rag_processing:
  enabled: true
  output_directory: "rag_output"
  save_intermediate: true
  parallel_processing: true
  max_workers: 4
  
  # LLM Configuration
  llm:
    type: "local"  # Options: "openai", "local"
    model: "llama3.2"  # For local LLM
    # api_key: "sk-..."  # Required for OpenAI
    batch_size: 5
    max_tokens: 150
    temperature: 0.1
    timeout: 30
  
  # Container Processing
  container_processor:
    enabled: true
    enable_llm_tagging: true
    cleaning_rules:
      container:
        - "custom_temporal_field"
        - "runtime_specific_data"
    
  # Future processors
  host_processor:
    enabled: true
    enable_llm_tagging: true
    
  service_processor:
    enabled: true
    enable_llm_tagging: true
```

### LLM Configuration Options

#### Local LLM (Default)
```yaml
llm:
  type: "local"
  model: "llama3.2"
  # Note: Local LLM integration not yet implemented
  # Currently uses rule-based fallback tagging
```

#### OpenAI API
```yaml
llm:
  type: "openai"
  model: "gpt-3.5-turbo"  # or "gpt-4"
  api_key: "sk-your-api-key-here"
  batch_size: 5
  max_tokens: 150
  temperature: 0.1
```

#### Environment Variables
Set sensitive configuration via environment variables:
```bash
export OPENAI_API_KEY="sk-your-api-key-here"
```

## Usage

### Command Line Interface

#### Full Pipeline (Recommended)
```bash
# Run complete pipeline: collection + RAG processing
python3 infrastructure_pipeline.py full-pipeline

# With debugging enabled
python3 infrastructure_pipeline.py full-pipeline --debug

# Process only container services
python3 infrastructure_pipeline.py full-pipeline --services-only
```

#### Separate Phases
```bash
# Run only collection phase
python3 infrastructure_pipeline.py collect

# Run only RAG processing phase (requires existing collected data)
python3 infrastructure_pipeline.py process

# Check pipeline status
python3 infrastructure_pipeline.py status
```

#### Legacy Support
```bash
# Use existing collection script (will be deprecated)
python3 run_collection.py

# Use existing analysis script (will be deprecated)  
python3 analyze_infrastructure.py
```

## RAG Processing Pipeline

### 4-Step Processing Pipeline

#### Step 1: Data Cleaning and Temporal Removal
**Purpose**: Remove temporal, status, and ephemeral information
**Process**:
- Removes runtime state (running/stopped, PIDs, timestamps)
- Removes health check logs and real-time metrics  
- Removes temporary IDs that change on restart
- Preserves persistent configuration and relationships

**Example Removed Fields**:
```yaml
Containers: [status, started_at, pid, health_check.status, stats]
Hosts: [uptime, cpu.usage_percent, memory.available, process_list]
Services: [active_state, main_pid, memory_current, last_trigger]
```

#### Step 2: Metadata Extraction and Relationship Mapping
**Purpose**: Extract structured metadata for programmatic queries
**Categories**:
- **Entity Properties**: name, image, ports, configuration
- **Relationships**: runs_on, depends_on, provides_to, config_files
- **Technical Specs**: networks, volumes, environment variables

**Relationship Types**:
- `runs_on`: which host/system runs this component
- `depends_on`: service/infrastructure dependencies  
- `provides_to`: what services this component enables
- `config_files`: configuration files affecting this component
- `networks`: network segments this component uses
- `volumes`: persistent storage relationships

#### Step 3: LLM-Based Semantic Tagging
**Purpose**: Generate human-intuitive tags for discovery
**Four Question Framework**:
1. **Generic Name**: "What is a common name for this container?" → `redis`, `database`, `proxy`
2. **Problem Solved**: "What problem does this solve?" → `caching`, `monitoring`, `authentication`  
3. **Infrastructure Role**: "What role in infrastructure?" → `middleware`, `security`, `observability`
4. **System Component**: "Part of what larger system?" → `authentik-system`, `monitoring-stack`

**Implementation**:
- Batch processing for efficiency
- Structured JSON output
- Fallback to rule-based tags if LLM fails
- Cost optimization through local LLM support

#### Step 4: RAG Data Assembly and Storage  
**Purpose**: Combine all data into final RAG format
**Output Structure**:
```json
{
  "id": "container_system_name",
  "type": "container",
  "title": "Human readable title",
  "content": "Detailed description with relationships",
  "metadata": {
    "entity_properties": {...},
    "relationships": {...}
  },
  "tags": ["semantic", "tags", "from", "llm"]
}
```

## Output Formats

### RAG Data Structure
```
rag_output/
├── containers.jsonl           # Container entities (JSONL format)
├── containers_metadata.json   # Processing metadata
└── intermediate/              # Debug data (if enabled)
    ├── container_system_name_intermediate.json
    └── ...
```

### JSONL Format
Each line is a complete JSON entity for streaming processing:
```jsonl
{"id": "container_web_redis", "type": "container", "title": "redis (caching)", ...}
{"id": "container_web_nginx", "type": "container", "title": "nginx (proxy)", ...}
```

### Processing Metadata
```json
{
  "extraction_timestamp": "20250906_122339",
  "processor_version": "1.0.0", 
  "entities_count": 45,
  "entity_types": ["container"],
  "llm_enabled": true,
  "parallel_processing": true
}
```

## Current Capabilities

### Supported Data Types
- ✅ **Docker Containers**: Full 4-step pipeline implemented
- 🔄 **Hosts/Systems**: Architecture ready, implementation pending
- 🔄 **Services**: Architecture ready, implementation pending
- 🔄 **Networks**: Architecture ready, implementation pending

### Container Processing Features
- **Temporal Data Removal**: Strips runtime state, preserves config
- **Relationship Detection**: Auto-detects dependencies from:
  - Docker Compose labels
  - Environment variables  
  - Network assignments
  - Volume mounts
  - Service references
- **Semantic Tagging**: Rule-based fallback with LLM-ready framework
- **Parallel Processing**: Multi-threaded for performance
- **Error Handling**: Comprehensive validation and recovery

### Investigation Workflows Enabled
- *"Show me all services that depend on this failing component"*
- *"What configuration files affect this problematic service?"*
- *"Find all monitoring components in my infrastructure"*
- *"Trace connectivity path from service A to service B"*

## Performance & Scalability

### Processing Performance
- **Parallel Processing**: 4 workers by default (configurable)
- **Batch LLM Processing**: 5 entities per API call (configurable)
- **Memory Efficient**: Streaming JSONL output
- **Progress Logging**: Detailed processing logs

### Current Limits
- **Dataset Size**: Tested with ~50 containers, designed for larger
- **Memory Usage**: Processes entities individually to minimize memory
- **LLM Costs**: Batch processing and fallback rules minimize API calls

### Scaling Considerations
```yaml
# High-volume configuration
rag_processing:
  parallel_processing: true
  max_workers: 8  # Increase for more containers
  llm:
    batch_size: 10  # Larger batches for efficiency
    type: "local"   # Avoid API costs
```

## Integration & Deployment

### Container Deployment Ready
The system is designed for containerized deployment:
- **Environment Variables**: Sensitive config via env vars
- **Volume Mounts**: Configurable output directories
- **Error Handling**: Container-safe error management
- **Logging**: Structured logging for container environments

### Integration Points
```python
# Programmatic usage
from src.config.settings import initialize_config
from src.processors.container_processor import ContainerProcessor

config = initialize_config()
processor = ContainerProcessor('containers', config.rag_processing.container_processor)
result = processor.process(collected_data)
```

### Pipeline Integration
```bash
# Daily/weekly automated processing
0 2 * * 1 /app/infrastructure_pipeline.py full-pipeline
```

## Troubleshooting

### Common Issues

#### Configuration Errors
```bash
# Error: "LLM client initialization failed"
# Solution: Check API key or disable LLM tagging
rag_processing:
  container_processor:
    enable_llm_tagging: false
```

#### Output Directory Issues
```bash
# Error: "Permission denied: rag_output"
# Solution: Ensure write permissions
chmod 755 rag_output
```

#### LLM API Issues  
```bash
# Error: "OpenAI API rate limit"
# Solution: Reduce batch size or add delays
llm:
  batch_size: 3
  timeout: 60
```

### Debug Mode
```bash
# Enable debug logging
python3 infrastructure_pipeline.py full-pipeline --debug

# Check intermediate files
ls -la rag_output/intermediate/
```

### Validation
```python
# Test processor configuration
python3 -c "
from src.config.settings import initialize_config
from src.processors.container_processor import ContainerProcessor
config = initialize_config()
processor = ContainerProcessor('test', config.rag_processing.container_processor)
print('Validation:', processor.validate_config())
"
```

## Future Enhancements

### Phase 2 Development
- **Host Processor**: System and hardware RAG extraction
- **Service Processor**: SystemD and service configuration RAG
- **Network Processor**: Network topology and configuration RAG
- **Local LLM Integration**: Complete local model support

### Phase 3 Features  
- **Real-time Updates**: Incremental processing for data changes
- **Quality Metrics**: Processing quality measurement and reporting
- **Advanced Relationships**: ML-based dependency inference
- **Multi-Environment**: Template system for different infrastructure types

### Integration Roadmap
- **Vector Database**: Integration with ChromaDB/Pinecone for semantic search
- **Conversational Interface**: Natural language query system
- **MCP Server**: Enhanced Model Context Protocol server for LLMs
- **Web Interface**: Dashboard for RAG data exploration

## Testing

### Unit Tests
```bash
# Test RAG processing pipeline
python3 test_rag_processor.py

# Test individual components
python3 -m pytest tests/processors/ -v
```

### Sample Queries
After processing, the RAG data enables queries like:
- Find all Redis instances: `tags: ["redis"]`
- Show web-stack components: `metadata.relationships.system_component: "web-stack"`  
- List middleware services: `tags: ["middleware"]`
- Find database dependencies: `metadata.relationships.depends_on: [*database*]`

### Validation Scenarios
- **Simple container failure**: Can system find config, host, dependencies?
- **Service connectivity issue**: Can system traverse network relationships?
- **Resource contention**: Can system identify competing services on same host?

## Support & Development

### Configuration Reference
See `src/config/settings.py` for complete configuration options and `RAGProcessingConfig` class definition.

### Extension Points
- **Custom Cleaning Rules**: Add processor-specific temporal field removal
- **Custom LLM Clients**: Implement `BaseLLMClient` for new LLM providers  
- **Custom Processors**: Extend `BaseProcessor` for new data types
- **Custom Relationships**: Add relationship extraction patterns

### Contributing
1. Create new processor by extending `BaseProcessor`
2. Implement 4-step pipeline in processor
3. Add processor configuration to `RAGProcessingConfig`
4. Update `infrastructure_pipeline.py` to use new processor
5. Add tests and documentation

This RAG processing pipeline provides the foundation for conversational infrastructure management while demonstrating AI-powered documentation principles applicable to any complex interconnected system.