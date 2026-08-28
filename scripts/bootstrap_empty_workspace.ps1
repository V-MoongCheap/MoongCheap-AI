$ErrorActionPreference = "Stop"

$directories = @(
  "data/raw/aihub/logistics_product",
  "data/raw/aihub/product_image",
  "data/raw/kan",
  "data/raw/mfds/I0030",
  "data/raw/mfds/I2710",
  "data/interim/category",
  "data/interim/products",
  "data/interim/facet_discovery",
  "data/processed/category",
  "data/processed/product_catalog",
  "data/processed/facet_discovery",
  "data/reports"
)

foreach ($directory in $directories) {
  New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot $directory) | Out-Null
}

Write-Output "Empty MoongCheap AI workspace initialized. Add source data under data/raw/."
