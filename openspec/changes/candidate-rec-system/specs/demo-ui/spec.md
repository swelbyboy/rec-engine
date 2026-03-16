## ADDED Requirements

### Requirement: Accept a JD via text input or file upload and return ranked profiles
The demo SHALL allow a user to submit a job description — either as pasted text or as an uploaded file — and receive a ranked list of recommended candidate profiles in response. No graphical UI is required at this stage; the API endpoint itself serves as the demo interface.

#### Scenario: User submits JD as raw text
- **WHEN** a user sends a POST request with raw JD text in the request body
- **THEN** the system returns a ranked list of recommended candidates with scores and explanations

#### Scenario: User uploads a JD file
- **WHEN** a user sends a POST request with a plain-text or PDF file attached
- **THEN** the system extracts the text, runs the pipeline, and returns ranked recommendations

#### Scenario: No candidates pass hard constraints
- **WHEN** the submitted JD eliminates all candidates via hard constraints
- **THEN** the response returns an empty ranked list with a clear message explaining that no candidates passed
