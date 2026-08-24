# Source me:  source design/env.sh
#
# Exports the sky130 PDK environment (PDK_ROOT / PDK) that design/xschemrc
# and design/regen_netlist.sh resolve, so an interactive `xschem` session
# sees exactly the same PDK pin as the mechanical netlist regeneration.
# Safe to source from any directory. Defaults mirror design/pdk.json.
#
#   PDK_ROOT   parent of the variant dir (open_pdks convention)
#   PDK        variant, e.g. sky130A

_gcedram_env_self="${BASH_SOURCE[0]:-${(%):-%x}}"
_gcedram_design_dir="$(cd "$(dirname "${_gcedram_env_self}")" && pwd)"

export PDK_ROOT="${PDK_ROOT:-$HOME/.volare}"
export PDK="${PDK:-sky130A}"

if [[ -f "${PDK_ROOT}/${PDK}/libs.tech/xschem/xschemrc" ]]; then
  echo "sky130-gcedram: PDK_ROOT=${PDK_ROOT} PDK=${PDK}"
else
  echo "sky130-gcedram: PDK not found at ${PDK_ROOT}/${PDK} -- see design/README.md for the install command (design/pdk.json)" >&2
fi

unset _gcedram_env_self _gcedram_design_dir
