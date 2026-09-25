"""Two policies the seed command installs. Edit them in admin afterwards."""

ANALYST = {
    "version": "1.0",
    "name": "analyst-us-east",
    "description": "Analysts see active US-East patients, no SSN, hashed email, masked name.",
    "permissions": {"canQuery": True, "readOnly": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {
            "hiddenFields": ["patients.ssn", "patients.date_of_birth"],
            "maskedFields": [
                {
                    "field": "patients.email",
                    "maskType": "hash",
                    "parameters": {"algorithm": "sha256"},
                },
                {
                    "field": "patients.full_name",
                    "maskType": "partial",
                    "parameters": {"showFirst": 1, "maskChar": "*"},
                },
            ],
        },
        "rowFilters": [
            {"field": "region", "operator": "equals", "value": "us-east"},
            {"field": "status", "operator": "notEquals", "value": "deleted"},
        ],
    },
    "limits": {"maxResults": 500},
}

AUDITOR = {
    "version": "1.0",
    "name": "auditor-all-regions",
    "description": "Auditors see every region but every identifying field is redacted.",
    "permissions": {"canQuery": True, "readOnly": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {
            "hiddenFields": ["patients.ssn"],
            "maskedFields": [
                {"field": "patients.email", "maskType": "redact"},
                {"field": "patients.full_name", "maskType": "redact"},
                {"field": "patients.date_of_birth", "maskType": "null"},
            ],
        },
        "rowFilters": [{"field": "status", "operator": "notEquals", "value": "deleted"}],
    },
    "limits": {"maxResults": 1000},
}
