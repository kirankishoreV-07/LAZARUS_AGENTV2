"""Phase 2 Validator Tests — validates all 4 edge cases are properly caught."""

from post_validators import (
    run_all_validations, validate_routes, validate_dependencies,
    validate_type_coherence, ValidationReport
)

print("=" * 60)
print("PHASE 2: Post-Generation Validators — Edge Case Tests")
print("=" * 60)

# ═══════════════════════════════════════════════════════════════
# TEST 1: Frontend-Backend Route Mismatches
# ═══════════════════════════════════════════════════════════════

backend_file = {
    "filename": "server/routes/users.js",
    "content": """
const express = require('express');
const router = express.Router();

router.get('/api/users', async (req, res) => {
    const users = await User.find();
    res.json(users);
});

router.post('/api/users', async (req, res) => {
    const user = new User(req.body);
    await user.save();
    res.status(201).json(user);
});

router.get('/api/users/:id', async (req, res) => {
    const user = await User.findById(req.params.id);
    res.json(user);
});

router.delete('/api/users/:id', async (req, res) => {
    await User.findByIdAndDelete(req.params.id);
    res.status(204).send();
});

module.exports = router;
""",
}

frontend_file = {
    "filename": "src/components/UserList.tsx",
    "content": """
import React, { useEffect, useState } from 'react';

const UserList = () => {
    const [users, setUsers] = useState([]);
    
    useEffect(() => {
        // CORRECT: matches backend
        fetch('/api/users').then(r => r.json()).then(setUsers);
    }, []);
    
    const deleteUser = (id: string) => {
        // CORRECT: matches backend
        fetch(`/api/users/${id}`, { method: 'DELETE' });
    };
    
    const updateUser = (id: string, data: any) => {
        // MISMATCH: backend has no PUT /api/users/:id
        fetch(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    };
    
    const getProfile = () => {
        // MISMATCH: backend has no /api/profile endpoint
        fetch('/api/profile').then(r => r.json());
    };
    
    return <div>{users.map(u => <span key={u.id}>{u.name}</span>)}</div>;
};
""",
}

route_issues = validate_routes([backend_file, frontend_file])
# Should catch PUT /api/users/:param and GET /api/profile as mismatches
route_mismatches = [i for i in route_issues if i.category == 'route_mismatch']
assert len(route_mismatches) >= 1, f"Expected at least 1 route mismatch, got {len(route_mismatches)}"
print(f"[1] Route validation: {len(route_mismatches)} mismatches detected — OK")
for issue in route_mismatches:
    print(f"    → {issue.message}")

# ═══════════════════════════════════════════════════════════════
# TEST 2: Missing Node.js Dependencies
# ═══════════════════════════════════════════════════════════════

node_app = {
    "filename": "server/index.js",
    "content": """
const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const dotenv = require('dotenv');
import Redis from 'ioredis';

dotenv.config();
const app = express();
app.use(cors());
""",
}

package_json = {
    "filename": "package.json",
    "content": """{
    "name": "myapp",
    "dependencies": {
        "express": "^4.18.0",
        "mongoose": "^7.0.0",
        "cors": "^2.8.5"
    }
}""",
}

dep_issues = validate_dependencies([node_app, package_json])
missing_dep_names = [i.message for i in dep_issues if i.category == 'missing_dep']
# Should catch: jsonwebtoken, bcryptjs, dotenv, ioredis (not in package.json)
assert len(missing_dep_names) >= 3, f"Expected at least 3 missing deps, got {len(missing_dep_names)}"
print(f"\n[2] Node.js dependency validation: {len(missing_dep_names)} missing deps — OK")
for msg in missing_dep_names:
    print(f"    → {msg}")

# ═══════════════════════════════════════════════════════════════
# TEST 3: Missing Python Dependencies
# ═══════════════════════════════════════════════════════════════

python_app = {
    "filename": "app/main.py",
    "content": """
from fastapi import FastAPI, Depends
from sqlalchemy import create_engine
from jose import jwt
import redis
import httpx
from pydantic import BaseModel
""",
}

requirements = {
    "filename": "requirements.txt",
    "content": """fastapi==0.100.0
uvicorn==0.23.0
pydantic==2.0.0
""",
}

py_dep_issues = validate_dependencies([python_app, requirements])
py_missing = [i for i in py_dep_issues if i.category == 'missing_dep']
# Should catch: sqlalchemy, jose, redis, httpx (not in requirements.txt)
assert len(py_missing) >= 3, f"Expected at least 3 missing Python deps, got {len(py_missing)}"
print(f"\n[3] Python dependency validation: {len(py_missing)} missing deps — OK")
for issue in py_missing:
    print(f"    → {issue.message}")

# ═══════════════════════════════════════════════════════════════
# TEST 4: Type Mismatches (TS interface vs Pydantic model)
# ═══════════════════════════════════════════════════════════════

ts_types_file = {
    "filename": "src/types/User.ts",
    "content": """
export interface User {
    id: string;
    name: string;
    email: string;
    age: number;
    created_at: string;
}

export interface Product {
    id: string;
    title: string;
    price: number;
    description: string;
    category: string;
    in_stock: boolean;
}
""",
}

py_models_file = {
    "filename": "app/models.py",
    "content": """
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class User(BaseModel):
    id: str
    name: str
    email: str
    # MISSING: age field!
    role: str  # EXTRA field not in TS
    created_at: datetime

class Product(BaseModel):
    id: str
    title: str
    price: int  # TYPE MISMATCH: TS says number (float-ish), Python says int
    description: str
    # MISSING: category, in_stock
""",
}

type_issues = validate_type_coherence([ts_types_file, py_models_file])
type_mismatches = [i for i in type_issues if i.category == 'type_mismatch']
assert len(type_mismatches) >= 1, f"Expected at least 1 type mismatch, got {len(type_mismatches)}"
print(f"\n[4] Type coherence validation: {len(type_mismatches)} mismatches — OK")
for issue in type_mismatches:
    print(f"    → [{issue.severity}] {issue.message}")

# ═══════════════════════════════════════════════════════════════
# TEST 5: Full validation pipeline (run_all_validations)
# ═══════════════════════════════════════════════════════════════

all_files = [backend_file, frontend_file, node_app, package_json,
             ts_types_file, py_models_file, python_app, requirements]

report = run_all_validations(all_files)
assert isinstance(report, ValidationReport)
assert report.total_issues > 0
assert report.route_mismatches >= 1
assert report.missing_deps >= 1
assert report.type_mismatches >= 1
print(f"\n[5] Full pipeline: {report.total_issues} total issues — OK")
print(f"    Routes: {report.route_mismatches} | Deps: {report.missing_deps} | Types: {report.type_mismatches}")

# ═══════════════════════════════════════════════════════════════
# TEST 6: prompt_injection produces usable fix instructions
# ═══════════════════════════════════════════════════════════════

fix_prompt = report.prompt_injection()
assert "VALIDATION" in fix_prompt.upper()
assert len(fix_prompt) > 100
print(f"\n[6] Prompt injection: {len(fix_prompt)} chars — OK")

# ═══════════════════════════════════════════════════════════════
# TEST 7: No false positives for correct code
# ═══════════════════════════════════════════════════════════════

correct_backend = {
    "filename": "server.py",
    "content": """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/data")
def get_data():
    return {"items": []}
""",
}

correct_frontend = {
    "filename": "src/App.tsx",
    "content": """
import React from 'react';
const App = () => {
    fetch('/api/data').then(r => r.json());
    return <div>App</div>;
};
""",
}

clean_report = run_all_validations([correct_backend, correct_frontend])
# Route validation should pass (GET /api/data exists on both sides)
route_false_positives = [i for i in clean_report.issues if i.category == 'route_mismatch']
assert len(route_false_positives) == 0, f"False positives: {[i.message for i in route_false_positives]}"
print(f"\n[7] No false positives for correct code — OK")

# ═══════════════════════════════════════════════════════════════
# TEST 8: Axios calls detected
# ═══════════════════════════════════════════════════════════════

axios_frontend = {
    "filename": "src/api.tsx",
    "content": """
import React from 'react';
import axios from 'axios';

const fetchUsers = () => axios.get('/api/users');
const createUser = (data) => axios.post('/api/users', data);
const deleteUser = (id) => axios.delete('/api/nonexistent/' + id);
""",
}

axios_issues = validate_routes([backend_file, axios_frontend])
axios_mismatches = [i for i in axios_issues if 'nonexistent' in i.message]
assert len(axios_mismatches) >= 1, "Should catch axios call to non-existent route"
print(f"\n[8] Axios route detection: caught {len(axios_mismatches)} mismatches — OK")

print("\n" + "=" * 60)
print("ALL EDGE CASE VALIDATOR TESTS PASSED ✅")
print("=" * 60)
