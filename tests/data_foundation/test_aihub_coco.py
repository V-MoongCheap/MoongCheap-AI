import json

from moongcheap_ai.parts.aihub import read_coco_json


def test_read_coco_json_flattens_product_attributes(tmp_path):
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps(
            {
                "images": [{"id": 7, "file_name": "product.jpg"}],
                "categories": [{"id": 3, "name": "01_food"}],
                "annotations": [
                    {
                        "id": 9,
                        "image_id": 7,
                        "category_id": 3,
                        "attributes": {
                            "product_name": "테스트 상품 2kg",
                            "barcode": "0123456789012",
                            "KAN_code": "01010101",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = read_coco_json(source)

    assert len(result) == 1
    assert result.loc[0, "product_name"] == "테스트 상품 2kg"
    assert result.loc[0, "barcode"] == "0123456789012"
    assert result.loc[0, "product_category"] == "01_food"
    assert result.loc[0, "image_filename"] == "product.jpg"
