# Entity Schema Directory

This directory contains YAML schema definitions for all entity types in the RAG data model.

## Purpose

Schema files define the structure, types, and validation rules for entities in `rag_output/rag_data.json`. They are used by the generic validation test to ensure data consistency.

## Schema Format

Each schema file uses YAML format with the following structure:

```yaml
entity_type: <entity_type_name>
description: <entity description>

# Root level fields (id, type)
root:
  <field_name>:
    type: <string|integer|float|boolean|array|object>
    required: <true|false>
    nullable: <true|false>
    enum: [value1, value2, ...]  # optional
    pattern: <regex_pattern>     # optional
    description: <field description>

# Tier 1: Vector Search Content (title, content)
tier1:
  <field_name>:
    type: string
    required: true
    min_length: <number>  # optional
    description: <field description>

# Tier 2: Summary Metadata
tier2:
  metadata:
    type: object
    required: true
    fields:
      <field_name>:
        type: <type>
        required: <true|false>
        nullable: <true|false>
        # ... additional constraints

# Tier 3: Detailed Information
tier3:
  details:
    type: object
    required: true
    fields:
      <field_name>:
        type: <type|object|array>
        # For objects:
        fields:
          <nested_field>: ...
        # For arrays:
        item_schema:
          type: object
          fields:
            <item_field>: ...
```

## Field Types

- `string`: Text values
- `integer`: Whole numbers
- `float`: Decimal numbers (also accepts integers)
- `boolean`: true/false
- `array`: List of items
- `object`: Nested structure

## Constraints

- `required`: Field must be present (default: false)
- `nullable`: Field can be null (default: false)
- `enum`: Value must be one of the specified options
- `pattern`: Value must match regex pattern (strings only)
- `min_length`: Minimum string length
- `format`: Special format validation (e.g., `iso8601`)

## Available Schemas

- `physical_server_entity.yml` - Physical server infrastructure

## Usage

Validate documents against a schema:

```bash
# From project root
python3 tests/test_entity_schema.py schema/physical_server_entity.yml
```

The test will:
1. Load the schema file
2. Find all documents in `rag_output/rag_data.json` matching the entity type
3. Validate each document against the schema
4. Report errors and warnings

## Adding New Schemas

1. Create a new YAML file in this directory: `<entity_type>_entity.yml`
2. Define the schema following the format above
3. Implement the corresponding processor to generate documents
4. Run validation: `python3 tests/test_entity_schema.py schema/<entity_type>_entity.yml`

## Schema Best Practices

1. **Be Explicit**: Always specify `required` and `nullable` for clarity
2. **Use Enums**: Define allowed values for fields with limited options
3. **Add Descriptions**: Document the purpose of each field
4. **Include Examples**: Provide example values for complex fields
5. **Validate Early**: Run schema validation after implementing each entity type
6. **Keep It Versioned**: Schema files are version controlled with the code
