# Revit MCP for MEP (Mechanical, Electrical, Plumbing)

## Executive Summary

Revit MCP for MEP defines an open standard that enables AI assistants to understand, analyze, and modify MEP systems in Revit models through a consistent protocol. It focuses on MEP-specific data models (ducts, pipes, conduits, cable trays, fittings, equipment, connectors, circuits, and systems) and operations (routing, connection, sizing, balancing, documentation) with security, auditability, and transaction safety.

This document provides structure, components, and implementation guidelines for a Revit MCP server specialized for MEP workflows.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Core Architecture](#2-core-architecture)
3. [MEP Data Models and Schemas](#3-mep-data-models-and-schemas)
4. [MEP API Endpoints and Operations](#4-mep-api-endpoints-and-operations)
5. [Security and Permissions](#5-security-and-permissions)
6. [Integration with Revit MEP API](#6-integration-with-revit-mep-api)
7. [Implementation Components](#7-implementation-components)
8. [Extension Points](#8-extension-points)
9. [Deployment Models](#9-deployment-models)
10. [Implementation Guidelines](#10-implementation-guidelines)
11. [MEP Use Cases and Examples](#11-mep-use-cases-and-examples)
12. [References](#12-references)

## 1. Introduction

### 1.1 Purpose

Provide a standardized, discipline-aware interface for exposing MEP system data and operations in Revit to AI assistants. The protocol abstracts Revit MEP APIs into domain concepts like systems, connectors, curves, equipment, circuits, and sizing parameters.

### 1.2 Background

Built on Anthropic’s Model Context Protocol (MCP), this specialization maps MEP entities and workflows to an AI-accessible API while retaining strong controls and audit trails.

### 1.3 Benefits

- Discipline-specific integration for Mechanical, Electrical, and Plumbing
- AI-assisted routing, connection, sizing, balancing, and documentation
- Consistent, typed schemas for MEP elements and systems
- Safer modifications via transactions and permission controls
- Reusable patterns across projects and firms

### 1.4 Scope

- MEP data models: systems, curves, fittings, equipment, connectors, circuits, spaces/zones
- MEP operations: query, route, connect, size, analyze, balance, document
- Security, transactions, and performance considerations for MEP-heavy models

## 2. Core Architecture

### 2.1 Client-Server Architecture

- MCP Host: AI application initiating requests
- MCP Client: Forwards host requests to the server and handles auth
- MCP Server: Maps MCP operations to Revit MEP API calls
- Revit Application: Revit instance with the MEP model

![MCP Architecture Diagram](architecture_diagram.png)

### 2.2 Communication Flow

1) Host -> Client -> Server  
2) Server -> Revit MEP API (transactions)  
3) Responses flow back to Host

### 2.3 Key Components

- MCP Host: general AI or MEP-focused assistant
- MCP Client: connection, request/response, auth
- MCP Server (MEP): endpoint registry, transactions, schema conversion
- Revit Integration: event handling, failure pre-processing, routing preferences

## 3. MEP Data Models and Schemas

Note: Units are SI by default unless specified (length: meters, diameter: meters, flow: L/s, pressure: Pa, power: W). Include a “units” block when using other units.

### 3.1 Connector

```json
{
  "connectorId": "c-abc123",
  "ownerElementId": "345678",
  "domain": "Mechanical|Piping|Electrical",
  "shape": "Round|Rectangular|Undefined",
  "diameter": 0.3,
  "width": 0.5,
  "height": 0.3,
  "flow": 1.2,
  "pressure": 250,
  "temperature": 294.15,
  "systemType": "SupplyAir|ReturnAir|ExhaustAir|HydronicSupply|HydronicReturn|Sanitary|DomesticCold|DomesticHot|Power|Data",
  "direction": "In|Out|Bidirectional",
  "coordinateSystem": {
    "origin": {"x": 10.0, "y": 2.0, "z": 3.2},
    "basisX": {"x": 1, "y": 0, "z": 0},
    "basisY": {"x": 0, "y": 1, "z": 0},
    "basisZ": {"x": 0, "y": 0, "z": 1}
  }
}
```

### 3.2 MEPCurve (Duct/Pipe/CableTray/Conduit)

```json
{
  "elementId": "567890",
  "category": "Ducts|Pipes|CableTrays|Conduits",
  "typeId": "300123",
  "systemId": "sys-001",
  "curve": {
    "start": {"x": 0, "y": 0, "z": 3.0},
    "end": {"x": 5.0, "y": 0, "z": 3.0}
  },
  "shape": "Round|Rectangular",
  "diameter": 0.25,
  "width": 0.45,
  "height": 0.3,
  "slope": 0.01,
  "insulation": {"thickness": 0.025, "material": "Fiberglass"},
  "lining": {"thickness": 0.013, "material": "Acoustic"},
  "parameters": {"Comments": "Main supply"}
}
```

### 3.3 Fitting

```json
{
  "elementId": "f-2222",
  "category": "DuctFittings|PipeFittings|CableTrayFittings|ConduitFittings",
  "typeId": "301234",
  "systemId": "sys-001",
  "fittingType": "Elbow|Tee|Cross|Transition|Tap|Union",
  "connectors": ["c-1", "c-2", "c-3"],
  "parameters": {"Angle": 90, "Radius": 0.3}
}
```

### 3.4 Equipment/Fixture/Device

```json
{
  "elementId": "e-1001",
  "category": "MechanicalEquipment|PlumbingFixtures|ElectricalEquipment|LightingDevices",
  "family": "Air Handling Unit",
  "type": "AHU-20k-CFM",
  "systemIds": ["sys-001", "sys-ctrl-01"],
  "connectors": ["c-inlet", "c-outlet"],
  "parameters": {
    "Airflow": 9.4,
    "StaticPressure": 500,
    "Power": 5000,
    "Voltage": 480
  }
}
```

### 3.5 System

```json
{
  "systemId": "sys-001",
  "domain": "Mechanical|Piping|Electrical",
  "systemType": "SupplyAir|ReturnAir|ExhaustAir|Hydronic|Sanitary|Domestic|Power|Lighting|Data",
  "name": "SA-Level2-East",
  "elements": ["e-1001", "567890", "f-2222"],
  "primaryEquipmentId": "e-1001",
  "calculated": {
    "totalFlow": 9.4,
    "pressureDrop": 350,
    "diversityFactor": 0.9,
    "demandLoad": 48000
  }
}
```

### 3.6 Electrical Circuit

```json
{
  "circuitId": "cir-101",
  "panelId": "e-panel-L2",
  "voltage": 277,
  "phase": "Single|Three",
  "connectedLoad": 3200,
  "elements": ["light-1", "light-2", "rec-1"]
}
```

### 3.7 Space/Zone Summary

```json
{
  "spaceId": "sp-204",
  "name": "Conference 2A",
  "level": "Level 2",
  "area": 42.0,
  "volume": 126.0,
  "environment": {"coolingLoad": 5400, "heatingLoad": 3800, "ventilation": 0.15}
}
```

## 4. MEP API Endpoints and Operations

Operations return { success, result, message } envelopes. All modification endpoints run inside Revit transactions.

### 4.1 Query Operations

- GetMEPElement: by elementId (returns typed MEP schema)
- QueryMEPElements: by category, systemType, level, parameters, bbox
- GetConnectors: for an elementId
- GetSystem: by systemId
- QuerySystems: by domain/systemType/name
- GetCircuit / QueryCircuits: panel, voltage, phase
- GetSpaces / QuerySpaces: by level/zone
- GetRoutingPreferences: for a domain/type

Example:
```json
{
  "operation": "GetSystem",
  "parameters": { "systemId": "sys-001" }
}
```

### 4.2 Modification Operations

- CreateDuct | CreatePipe | CreateCableTray | CreateConduit
- ConnectElements: connect two connectors with auto fitting
- RoutePath: autoroute between connectors with rules
- AddFitting: elbow/tee/transition/tap
- SetCurveSize: set diameter/width/height
- SetSlope: for pipes
- ApplyInsulation | ApplyLining
- PlaceEquipment/Fixture/Device
- SizeSystem: compute and set sizes from flow/load targets
- RebuildSystem: recompute connections/handedness/flow direction

Example:
```json
{
  "operation": "RoutePath",
  "parameters": {
    "fromConnectorId": "c-ah1-out",
    "toConnectorId": "c-vav-03-in",
    "domain": "Mechanical",
    "rules": {
      "preferredShape": "Round",
      "maxVelocity": 7.5,
      "maxPressureDropPerM": 2.0,
      "avoidCategories": ["StructuralFraming"],
      "clearances": {"min": 0.05}
    }
  }
}
```

### 4.3 Analysis Operations

- ComputePressureDrop: per segment/system
- ComputeFlowDistribution: solve network flow
- BalanceAirSystem / BalanceHydronicSystem
- CheckInterference: MEP-vs-Structure/Arch
- ValidateConnectivity: open ends, mismatched connectors
- AggregateLoads: space->zone->system
- ElectricalLoadSummary: connected vs demand

Example:
```json
{
  "operation": "ValidateConnectivity",
  "parameters": { "systemId": "sys-001", "reportOpenEnds": true }
}
```

### 4.4 Documentation Operations

- CreateMEPTag: element/system tags with parameters
- GenerateSchedules: duct/pipe/equipment/device/circuit
- CreateSingleLineDiagram: simplified system diagram view
- ColorBySystem: view filters by system/domain/flow
- AnnotateSlopes: pipe slope markers
- PlacePanelSchedules: electrical panel schedule views

Example:
```json
{
  "operation": "GenerateSchedules",
  "parameters": {
    "categories": ["Ducts", "MechanicalEquipment"],
    "fields": ["Type", "Length", "Diameter", "Airflow"],
    "filters": [{"field": "Level", "operator": "equals", "value": "Level 2"}],
    "name": "Level 2 HVAC Schedule"
  }
}
```

### 4.5 Advanced Operations

- ExecuteMEPCode: restricted C# snippets with MEP API access
- RunTransaction: batch operations with rollback
- ImportMEPData: CSV/JSON of equipment lists, setpoints, panel boards
- ExportMEPData: BOMs, schedules, connection graphs

## 5. Security and Permissions

- Authentication: local/remote tokens, optional SSO proxies
- Authorization:
  - Read: query-only
  - Write: modify specific categories/systems
  - Admin: routing prefs, code execution, server settings
- Data Protection: redact client names/addresses if required, audit logs per operation, PII scrubbing for exports

## 6. Integration with Revit MEP API

### 6.1 API Mapping

- Mechanical: Autodesk.Revit.DB.Mechanical (Duct, DuctFitting, MechanicalSystem)
- Piping: Autodesk.Revit.DB.Plumbing (Pipe, PipeFitting, PipingSystem)
- Electrical: Autodesk.Revit.DB.Electrical (Conduit, CableTray, ElectricalSystem, Circuit)
- Common:
  - MEPCurve, Connector/ConnectorManager
  - MEPSystem, RoutingPreferenceManager
  - FamilyInstance.MEPModel

### 6.2 Transactions and Failures

- Use Transaction / SubTransaction for grouped actions
- FailurePreprocessor to auto-resolve benign warnings (e.g., slight adjustments)
- Rollback on routing failures or connector mismatches

### 6.3 Performance Considerations

- FilteredElementCollector by category and class (MEPCurve, FamilyInstance)
- Limit geometric calculations; prefer system graph traversal
- Batch sizing updates; defer regen when possible
- Cache routing preferences and type lookups
- Use view-based visibility filters for large queries

## 7. Implementation Components

- RevitMCPMEPServer: main add-in hosting MCP endpoints
- RevitMEPConnector: typed helpers for MEP API
- SchemaConverters.MEP: element<->schema mappings
- Endpoints:
  - QueryMEPEndpoints
  - ModifyMEPEndpoints
  - AnalysisMEPEndpoints
  - DocumentationMEPEndpoints
- Security: AuthN/AuthZ/Audit
- Utils: Units, RoutingRules, Graph traversal

## 8. Extension Points

- Custom Routing Policies: velocity caps, material preferences, elevation bands
- Custom Sizing Algorithms: ductulator rules, equal friction, static regain
- Discipline Plugins: Fire Protection, Specialty Gas, Low Voltage
- SchemaExtensions: firm-specific parameters and classifications (e.g., Uniclass/OmniClass)

## 9. Deployment Models

- Local Desktop: Revit add-in hosting MCP server for a running model
- Remote/VDI: Server runs where Revit is installed; client communicates over a secure channel
- Hybrid: Local read-only with escalated write via approval queue

## 10. Implementation Guidelines

### 10.1 Server Setup (Windows/Revit)

Prereqs:
- Visual Studio 2022+
- .NET Framework 4.8 or .NET 6+ (with Revit-compatible shim)
- Revit API SDK
- MCP SDK for .NET

Project structure:
```
RevitMCPMEPServer/
├── Core/
│   ├── RevitMEPConnector.cs
│   ├── SchemaConverter.MEP.cs
│   └── TransactionManager.cs
├── Endpoints/
│   ├── QueryMEPEndpoints.cs
│   ├── ModifyMEPEndpoints.cs
│   ├── AnalysisMEPEndpoints.cs
│   └── DocumentationMEPEndpoints.cs
├── Security/
│   ├── Authentication.cs
│   └── Authorization.cs
└── RevitMCPMEPServerPlugin.cs
```

Example: GetSystem endpoint outline
```csharp
// Pseudocode: Query a system and map to schema
public EndpointResponse Execute(EndpointRequest req, RevitMEPConnector conn)
{
    var id = req.Parameters["systemId"].ToString();
    var sys = conn.GetSystemByStableId(id);
    if (sys == null) return Fail($"System {id} not found");
    var schema = SchemaConverterMEP.ToSystemSchema(sys);
    return Ok(schema);
}
```

Error patterns:
- NoRouteFound, ConnectorMismatch, InvalidSystemType, TypeNotFound, ClearanceViolation

### 10.2 Client (Cross-Platform)

A Python MCP client can be developed/tested in this container to call a Windows-hosted server. See examples in Use Cases for payloads.

### 10.3 Testing

- Unit tests for schema conversion and parameter mapping
- Integration tests mocking MEPCurve graphs
- Golden tests for sizing and routing policies

## 11. MEP Use Cases and Examples

### 11.1 HVAC: Route and Size a Branch

User: “Connect VAV-03 to SA main with round duct, max velocity 7.5 m/s.”

Request:
```json
{
  "operation": "RoutePath",
  "parameters": {
    "fromConnectorId": "c-SA-main-near",
    "toConnectorId": "c-VAV-03-in",
    "domain": "Mechanical",
    "rules": {"preferredShape": "Round", "maxVelocity": 7.5}
  }
}
```
Followed by:
```json
{
  "operation": "SizeSystem",
  "parameters": {"systemId": "sys-SA-L2", "method": "EqualFriction", "target": {"friction": 0.8}}
}
```

### 11.2 Plumbing: Slope and Connect Sanitary

```json
{
  "operation": "CreatePipe",
  "parameters": {
    "start": {"x": 10, "y": 3, "z": 2.8},
    "end": {"x": 6, "y": 3, "z": 2.7},
    "systemType": "Sanitary",
    "typeId": "pipeType-PVC-100"
  }
}
```
Then:
```json
{
  "operation": "SetSlope",
  "parameters": {"elementId": "567890", "slope": 0.02}
}
```

### 11.3 Electrical: Circuit and Schedule

```json
{
  "operation": "GetCircuit",
  "parameters": {"circuitId": "cir-101"}
}
```
```json
{
  "operation": "GenerateSchedules",
  "parameters": {
    "categories": ["ElectricalEquipment", "LightingDevices"],
    "fields": ["Panel", "CircuitNumber", "ConnectedLoad", "Voltage"],
    "name": "L2 Lighting Circuits"
  }
}
```

### 11.4 QA: Validate Connectivity and Interference

```json
{
  "operation": "ValidateConnectivity",
  "parameters": {"systemId": "sys-001", "reportOpenEnds": true}
}
```
```json
{
  "operation": "CheckInterference",
  "parameters": {"categoriesA": ["Ducts"], "categoriesB": ["StructuralFraming"], "tolerance": 0.01}
}
```

## 12. References

- Model Context Protocol: https://modelcontextprotocol.io/
- Revit API Developer’s Guide: https://www.autodesk.com/developer-network/platform-technologies/revit
- Revit API Namespaces:
  - Mechanical: Autodesk.Revit.DB.Mechanical
  - Plumbing: Autodesk.Revit.DB.Plumbing
  - Electrical: Autodesk.Revit.DB.Electrical
- The Building Coder: Revit MEP samples and best practices
