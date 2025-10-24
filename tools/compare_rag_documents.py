#!/usr/bin/env python3
"""
Compare RAG documents between backup and current rag_data.json files.
Reports missing documents and differences in content.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Set
from difflib import unified_diff


def load_rag_data(file_path: str) -> Dict[str, Any]:
    """Load RAG data from JSON file"""
    with open(file_path, 'r') as f:
        return json.load(f)


def get_document_by_id(documents: List[Dict], doc_id: str) -> Dict[str, Any]:
    """Find a document by its ID"""
    for doc in documents:
        if doc.get('id') == doc_id:
            return doc
    return None


def find_similar_document(documents: List[Dict], doc_id: str) -> Dict[str, Any]:
    """
    Find a document by ID, accounting for system name changes like:
    - container_unraid-server_X -> container_unraid-server-unified_X
    - container_server-containers_X -> container_server-containers-unified_X
    """
    # First try exact match
    exact_match = get_document_by_id(documents, doc_id)
    if exact_match:
        return exact_match, "exact"

    # Try adding -unified suffix to system name
    # Pattern: {type}_{system}_{name} -> {type}_{system}-unified_{name}
    parts = doc_id.split('_', 2)
    if len(parts) >= 3:
        doc_type, system, name = parts
        unified_id = f"{doc_type}_{system}-unified_{name}"
        unified_match = get_document_by_id(documents, unified_id)
        if unified_match:
            return unified_match, "unified_suffix"

    return None, None


def compare_values(path: str, val1: Any, val2: Any, differences: List[str]):
    """Recursively compare two values and track differences"""
    if type(val1) != type(val2):
        differences.append(f"  {path}: Type mismatch - {type(val1).__name__} vs {type(val2).__name__}")
        return

    if isinstance(val1, dict):
        keys1 = set(val1.keys())
        keys2 = set(val2.keys())

        # Keys only in val1
        for key in keys1 - keys2:
            differences.append(f"  {path}.{key}: Only in backup")

        # Keys only in val2
        for key in keys2 - keys1:
            differences.append(f"  {path}.{key}: Only in current")

        # Compare common keys
        for key in keys1 & keys2:
            compare_values(f"{path}.{key}", val1[key], val2[key], differences)

    elif isinstance(val1, list):
        if len(val1) != len(val2):
            # For tags, show what's different
            if 'tags' in path:
                set1 = set(val1) if all(isinstance(x, str) for x in val1) else val1
                set2 = set(val2) if all(isinstance(x, str) for x in val2) else val2
                if isinstance(set1, set) and isinstance(set2, set):
                    only_in_backup = set1 - set2
                    only_in_current = set2 - set1
                    differences.append(f"  {path}: Backup has {len(val1)} tags, Current has {len(val2)} tags")
                    if only_in_backup:
                        differences.append(f"    Only in backup: {only_in_backup}")
                    if only_in_current:
                        differences.append(f"    Only in current: {only_in_current}")
                else:
                    differences.append(f"  {path}: List length mismatch - {len(val1)} vs {len(val2)}")
            else:
                differences.append(f"  {path}: List length mismatch - {len(val1)} vs {len(val2)}")
        else:
            for i, (item1, item2) in enumerate(zip(val1, val2)):
                compare_values(f"{path}[{i}]", item1, item2, differences)

    else:
        if val1 != val2:
            # Truncate long values for readability
            str_val1 = str(val1)[:100]
            str_val2 = str(val2)[:100]
            if len(str(val1)) > 100:
                str_val1 += "..."
            if len(str(val2)) > 100:
                str_val2 += "..."
            differences.append(f"  {path}: '{str_val1}' != '{str_val2}'")


def calculate_document_size(doc: Dict[str, Any]) -> int:
    """Calculate the total size of a document in characters"""
    return len(json.dumps(doc, default=str))


def compare_document_sizes(doc1: Dict[str, Any], doc2: Dict[str, Any], tolerance_pct: float = 5.0) -> Dict[str, Any]:
    """
    Compare document sizes with tolerance

    Args:
        doc1: Backup document
        doc2: Current document
        tolerance_pct: Percentage tolerance (default 5%)

    Returns:
        Dict with size comparison results
    """
    size1 = calculate_document_size(doc1)
    size2 = calculate_document_size(doc2)

    # Calculate percentage difference
    if size1 == 0:
        pct_diff = 100.0 if size2 > 0 else 0.0
    else:
        pct_diff = ((size2 - size1) / size1) * 100.0

    within_tolerance = abs(pct_diff) <= tolerance_pct

    return {
        'backup_size': size1,
        'current_size': size2,
        'size_diff': size2 - size1,
        'pct_diff': pct_diff,
        'within_tolerance': within_tolerance,
        'tolerance_pct': tolerance_pct
    }


def compare_documents(doc1: Dict[str, Any], doc2: Dict[str, Any]) -> List[str]:
    """Compare two documents and return list of differences"""
    differences = []

    # Compare top-level keys
    keys1 = set(doc1.keys())
    keys2 = set(doc2.keys())

    if keys1 != keys2:
        only_in_backup = keys1 - keys2
        only_in_current = keys2 - keys1
        if only_in_backup:
            differences.append(f"  Keys only in backup: {only_in_backup}")
        if only_in_current:
            differences.append(f"  Keys only in current: {only_in_current}")

    # Compare common fields
    for key in keys1 & keys2:
        compare_values(key, doc1[key], doc2[key], differences)

    return differences


def compare_rag_files(backup_path: str, current_path: str, sample_size: int = 5):
    """Compare documents between backup and current RAG files"""

    print(f"Loading RAG data files...")
    print(f"  Backup: {backup_path}")
    print(f"  Current: {current_path}")
    print()

    # Load both files
    backup_data = load_rag_data(backup_path)
    current_data = load_rag_data(current_path)

    backup_docs = backup_data.get('documents', [])
    current_docs = current_data.get('documents', [])

    print(f"Document counts:")
    print(f"  Backup: {len(backup_docs)} documents")
    print(f"  Current: {len(current_docs)} documents")
    print()

    # Get document IDs
    backup_ids = {doc['id'] for doc in backup_docs if 'id' in doc}
    current_ids = {doc['id'] for doc in current_docs if 'id' in doc}

    print(f"Unique document IDs:")
    print(f"  Backup: {len(backup_ids)} unique IDs")
    print(f"  Current: {len(current_ids)} unique IDs")
    print()

    # Find missing documents
    missing_in_current = backup_ids - current_ids
    only_in_current = current_ids - backup_ids

    if missing_in_current:
        print(f"⚠️  Documents in backup but NOT in current: {len(missing_in_current)}")
        print(f"   Sample: {list(missing_in_current)[:10]}")
        print()

    if only_in_current:
        print(f"✅ New documents in current (not in backup): {len(only_in_current)}")
        print(f"   Sample: {list(only_in_current)[:10]}")
        print()

    # Compare sample documents
    print("=" * 80)
    if sample_size is None:
        print(f"Comparing ALL {len(backup_docs)} documents from backup...")
        sample_docs = backup_docs
        sample_size = len(backup_docs)
    else:
        print(f"Comparing {sample_size} sample documents from backup...")
        sample_docs = backup_docs[:sample_size]
    print("=" * 80)
    print()

    # Statistics tracking
    stats = {
        'total': 0,
        'found_exact': 0,
        'found_fuzzy': 0,
        'not_found': 0,
        'identical': 0,
        'different': 0,
        'size_within_tolerance': 0,
        'size_outside_tolerance': 0,
        'size_larger': 0,
        'size_smaller': 0
    }

    # Track documents with size issues
    size_issues = []

    for i, backup_doc in enumerate(sample_docs, 1):
        stats['total'] += 1
        doc_id = backup_doc.get('id', 'NO_ID')
        doc_type = backup_doc.get('type', 'NO_TYPE')

        print(f"[{i}/{sample_size}] Document: {doc_id}")
        print(f"  Type: {doc_type}")

        # Find in current (with fuzzy matching for system name changes)
        current_doc, match_type = find_similar_document(current_docs, doc_id)

        if current_doc is None:
            print(f"  ❌ NOT FOUND in current rag_data.json (even with fuzzy matching)")
            stats['not_found'] += 1
            print()
            continue

        if match_type == "unified_suffix":
            print(f"  📝 FOUND with modified ID: {current_doc['id']}")
            stats['found_fuzzy'] += 1
        else:
            print(f"  ✅ FOUND with exact ID")
            stats['found_exact'] += 1

        # Compare document sizes
        size_comparison = compare_document_sizes(backup_doc, current_doc, tolerance_pct=5.0)

        print(f"  📏 Size: Backup={size_comparison['backup_size']} chars, Current={size_comparison['current_size']} chars")
        print(f"      Diff: {size_comparison['size_diff']:+d} chars ({size_comparison['pct_diff']:+.1f}%)")

        if size_comparison['within_tolerance']:
            print(f"      ✅ Within ±{size_comparison['tolerance_pct']}% tolerance")
            stats['size_within_tolerance'] += 1
        else:
            print(f"      ⚠️  OUTSIDE ±{size_comparison['tolerance_pct']}% tolerance")
            stats['size_outside_tolerance'] += 1
            size_issues.append({
                'doc_id': doc_id,
                'doc_type': doc_type,
                **size_comparison
            })

        if size_comparison['size_diff'] > 0:
            stats['size_larger'] += 1
        elif size_comparison['size_diff'] < 0:
            stats['size_smaller'] += 1

        # Compare documents
        differences = compare_documents(backup_doc, current_doc)

        if not differences:
            print(f"  ✅ IDENTICAL - No differences found")
            stats['identical'] += 1
        else:
            print(f"  ⚠️  DIFFERENCES FOUND ({len(differences)} differences):")
            stats['different'] += 1
            for diff in differences[:20]:  # Limit to first 20 differences
                print(diff)
            if len(differences) > 20:
                print(f"  ... and {len(differences) - 20} more differences")

        print()

    # Summary
    print("=" * 80)
    print("Summary:")
    print("=" * 80)
    print(f"📊 Documents compared: {stats['total']}")
    print(f"   ✅ Found with exact ID: {stats['found_exact']}")
    print(f"   📝 Found with modified ID: {stats['found_fuzzy']}")
    print(f"   ❌ Not found: {stats['not_found']}")
    print()
    print(f"📋 Comparison results:")
    print(f"   ✅ Identical: {stats['identical']}")
    print(f"   ⚠️  Different: {stats['different']}")
    print()
    print(f"📏 Size comparison (±5% tolerance):")
    print(f"   ✅ Within tolerance: {stats['size_within_tolerance']}")
    print(f"   ⚠️  Outside tolerance: {stats['size_outside_tolerance']}")
    print(f"   📈 Larger in current: {stats['size_larger']}")
    print(f"   📉 Smaller in current: {stats['size_smaller']}")
    print()
    print(f"🔍 Overall statistics:")
    print(f"   ⚠️  Missing in current (not found with fuzzy match): {len(missing_in_current)}")
    print(f"   ✨ New in current: {len(only_in_current)}")
    print()

    # Report documents with size issues
    if size_issues:
        print("=" * 80)
        print(f"⚠️  Documents OUTSIDE ±5% size tolerance ({len(size_issues)} total):")
        print("=" * 80)
        print()

        # Group by document type
        by_type = {}
        for issue in size_issues:
            doc_type = issue['doc_type']
            if doc_type not in by_type:
                by_type[doc_type] = []
            by_type[doc_type].append(issue)

        for doc_type, issues in sorted(by_type.items()):
            print(f"\n{doc_type.upper()} ({len(issues)} documents):")
            print("-" * 80)

            # Sort by percentage difference (largest absolute difference first)
            issues_sorted = sorted(issues, key=lambda x: abs(x['pct_diff']), reverse=True)

            for issue in issues_sorted:
                direction = "📈 LARGER" if issue['size_diff'] > 0 else "📉 SMALLER"
                print(f"  {direction} {issue['doc_id']}")
                print(f"    Backup: {issue['backup_size']:,} chars")
                print(f"    Current: {issue['current_size']:,} chars")
                print(f"    Difference: {issue['size_diff']:+,} chars ({issue['pct_diff']:+.1f}%)")
                print()
    else:
        print("=" * 80)
        print("✅ All documents are within ±5% size tolerance!")
        print("=" * 80)
        print()


if __name__ == "__main__":
    backup_file = "rag_output/rag_data_backup.json"
    current_file = "rag_output/rag_data.json"

    # Check if files exist
    if not Path(backup_file).exists():
        print(f"❌ Backup file not found: {backup_file}")
        exit(1)

    if not Path(current_file).exists():
        print(f"❌ Current file not found: {current_file}")
        exit(1)

    # Compare ALL documents from backup
    compare_rag_files(backup_file, current_file, sample_size=None)
