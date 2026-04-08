#!/usr/bin/env bash
set -e

# Usage: install.sh <target> <skills_source> <guides_source> <skill1> <skill2> ...
# Example: install.sh /tmp/sdlc /path/to/agents/skills /path/to/agents commit implement issue pr review test understand-chat

if [ $# -lt 3 ]; then
	echo "✗ Error: insufficient arguments"
	echo "Usage: install.sh <target> <skills_source> <guides_source> <skill1> <skill2> ..."
	exit 1
fi

target="$1"
skills_source="$2"
guides_source="$3"
shift 3
skills=("$@")

mkdir -p "$target"
target_abs="$(realpath "$target")"
guides_abs="$(realpath "$guides_source")"
guides_abs_test="$(realpath "$guides_source/test-guides")"
guides_abs_style="$(realpath "$guides_source/style-guides")"

echo "Installing SDLC pipeline to $target/"

# Symlink guides (only if target is not the guides directory)
if [ "$target_abs" != "$guides_abs" ]; then
	echo ""
	echo "Symlinking guides..."
	for guide_dir in "$guides_source/test-guides" "$guides_source/style-guides"; do
		guide_name=$(basename "$guide_dir")
		target_guide="$target_abs/$guide_name"
		if [ -d "$target_guide" ] && [ -L "$target_guide" ]; then
			echo "  ✓ $guide_name (already symlinked)"
		else
			rm -rf "$target_guide"
			ln -s "$guide_dir" "$target_guide"
			echo "  → $guide_name"
		fi
	done
fi

# Symlink skills
echo ""
echo "Symlinking skills..."
for skill_name in "${skills[@]}"; do
	skill_dir="$skills_source/$skill_name"
	skill_dir_abs="$(realpath "$skill_dir")"
	target_skill_dir="$target/$skill_name"
	if [ -d "$target_skill_dir" ] && [ -L "$target_skill_dir" ]; then
		echo "  ✓ $skill_name (already symlinked)"
	else
		rm -rf "$target_skill_dir"
		ln -s "$skill_dir_abs" "$target_skill_dir"
		echo "  → $skill_name"
	fi
	ln -sf "$guides_abs_test" "$target_skill_dir/test-guides"
	ln -sf "$guides_abs_style" "$target_skill_dir/style-guides"
done

echo ""
echo "✓ Installation complete"
echo ""
echo "Verify with: ls -lh $target/"
