#!/usr/bin/env bash
set -e

# Usage: uninstall.sh <target> <skills_source> <guides_source> <skill1> <skill2> ...
# Example: uninstall.sh /tmp/sdlc /path/to/agents/skills /path/to/agents commit implement issue pr review test understand-chat

if [ $# -lt 3 ]; then
	echo "✗ Error: insufficient arguments"
	echo "Usage: uninstall.sh <target> <skills_source> <guides_source> <skill1> <skill2> ..."
	exit 1
fi

target="$1"
skills_source="$2"
guides_source="$3"
shift 3
skills=("$@")

if [ ! -d "$target" ]; then
	echo "⚠  Directory $target/ does not exist"
	exit 1
fi

echo "Removing SDLC pipeline from $target/"
echo ""

# Remove skills and their guide symlinks
echo "Removing skills and guide symlinks..."
for skill_name in "${skills[@]}"; do
	target_dir="$target/$skill_name"
	skill_dir="$skills_source/$skill_name"
	if [ -d "$target_dir" ] || [ -L "$target_dir" ]; then
		rm -rf "$target_dir"
		echo "  ✗ $skill_name removed"
	fi
	rm -f "$skill_dir/test-guides" "$skill_dir/style-guides"
done

# Remove guide symlinks from target
echo ""
echo "Removing guides..."
for guide_dir in "$guides_source/test-guides" "$guides_source/style-guides"; do
	guide_name=$(basename "$guide_dir")
	target_guide="$target/$guide_name"
	if [ -L "$target_guide" ]; then
		rm -f "$target_guide"
		echo "  ✗ $guide_name symlink removed"
	fi
done

echo ""
echo "✓ Uninstall complete"
