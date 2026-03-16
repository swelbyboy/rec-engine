## ADDED Requirements

### Requirement: Pipeline endpoint accepting JD text or file upload
The system SHALL expose `POST /recommend` accepting either raw JD text (JSON body) or a file upload (multipart form), and returning ranked candidate recommendations with scores and explanations. This endpoint is the primary demo interface.

#### Scenario: Raw JD text submitted
- **WHEN** a POST request is made with `{"jd_text": "..."}` in the JSON body
- **THEN** the endpoint extracts the JD, runs the full pipeline, and returns ranked candidates with scores and explanations

#### Scenario: JD file uploaded
- **WHEN** a POST request is made with a plain-text or PDF file as a multipart upload
- **THEN** the endpoint reads the file content, extracts the JD, runs the full pipeline, and returns ranked candidates

#### Scenario: No candidates pass hard constraints
- **WHEN** all candidates are eliminated by the constraint engine
- **THEN** the endpoint returns `{"ranked": [], "eliminated_count": N, "message": "No candidates passed hard constraints"}`

---

### Requirement: Health check endpoint
The system SHALL expose `GET /health` returning service status.

#### Scenario: Service is up
- **WHEN** `GET /health` is called
- **THEN** the endpoint returns `{"status": "ok"}` with HTTP 200

---

### Requirement: Preloaded candidate data loaded at startup
The system SHALL load the 20 candidate fixtures into memory at startup. The candidate pool is fixed for the demo — all JDs are matched against this same pool.

#### Scenario: Application starts
- **WHEN** the FastAPI application starts
- **THEN** all 20 candidate fixtures are in memory and ready for the pipeline to use
