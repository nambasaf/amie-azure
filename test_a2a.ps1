$GatewayUrl = "http://localhost:7075/api"

Write-Host "========================================="
Write-Host "   Testing AMIE A2A Gateway Locally"
Write-Host "========================================="
Write-Host ""

# 1. Test Agent Card
Write-Host "[1] Fetching Agent Card (GET /agent-card.json)..." -ForegroundColor Cyan
try {
    $card = Invoke-RestMethod -Uri "$GatewayUrl/agent-card.json" -Method Get
    $card | ConvertTo-Json -Depth 5
    Write-Host "Agent Card fetched successfully.`n" -ForegroundColor Green
}
catch {
    Write-Host "Failed to fetch agent card: $_`n" -ForegroundColor Red
}

# 2. Test Submit Manuscript (JSON-RPC)
Write-Host "[2] Submitting a Manuscript (POST /a2a)..." -ForegroundColor Cyan
Write-Host "Enter a public URL to a manuscript (PDF recommended)." 
$PdfUrl = Read-Host "Enter a valid Azure Blob URL to a PDF (or press Enter to skip submit test)"

if (![string]::IsNullOrWhiteSpace($PdfUrl)) {
    
    $submitPayload = @{
        jsonrpc = "2.0"
        method  = "submit_manuscript"
        params  = @{
            url               = $PdfUrl
            client_request_id = [guid]::NewGuid().ToString()
        }
        id      = "test-call-1"
    }

    $submitJson = $submitPayload | ConvertTo-Json

    try {
        $submitResponse = Invoke-RestMethod -Uri "$GatewayUrl/a2a" -Method Post -Body $submitJson -ContentType "application/json"
        
        Write-Host "Response:"
        $submitResponse | ConvertTo-Json -Depth 5
        
        if ($submitResponse.result -and $submitResponse.result.request_id) {
            $Global:TestRequestId = $submitResponse.result.request_id
            Write-Host "Manuscript submitted successfully! Request ID: $TestRequestId`n" -ForegroundColor Green
        }
        else {
            Write-Host "Submission returned an error.`n" -ForegroundColor Yellow
        }

    }
    catch {
        Write-Host "Failed to submit manuscript: $_`n" -ForegroundColor Red
    }
}
else {
    Write-Host "Skipping submit test.`n" -ForegroundColor DarkGray
}

# 3. Test Get Status (JSON-RPC)
Write-Host "[3] Checking Status (POST /a2a)..." -ForegroundColor Cyan
$StatusReqId = ""

if ($Global:TestRequestId) {
    $choice = Read-Host "Check status for the request we just generated ($TestRequestId)? (Y/n)"
    if ($choice -ne "n" -and $choice -ne "N") {
        $StatusReqId = $Global:TestRequestId
    }
}

if ([string]::IsNullOrWhiteSpace($StatusReqId)) {
    $StatusReqId = Read-Host "Enter a request_id to check (or press Enter to skip)"
}

if (![string]::IsNullOrWhiteSpace($StatusReqId)) {

    $maxAttempts = 30
    $attempt = 0

    while ($attempt -lt $maxAttempts) {

        $statusPayload = @{
            jsonrpc = "2.0"
            method  = "get_status"
            params  = @{
                request_id = $StatusReqId
            }
            id      = "poll-$attempt"
        }

        $statusJson = $statusPayload | ConvertTo-Json

        try {
            $statusResponse = Invoke-RestMethod -Uri "$GatewayUrl/a2a" -Method Post -Body $statusJson -ContentType "application/json"

            Write-Host "`nAttempt $($attempt + 1):"
            $statusResponse | ConvertTo-Json -Depth 5

            $rawStatus = $statusResponse.result.status.ToLower()

            if ($rawStatus -eq "completed") {
                Write-Host "`nPipeline completed successfully!" -ForegroundColor Green
                break
            }

            if ($rawStatus -eq "failed") {
                Write-Host "`nPipeline failed!" -ForegroundColor Red
                break
            }

            Write-Host "Still running... waiting 15 seconds..." -ForegroundColor Yellow
            Start-Sleep -Seconds 15
            $attempt++

        }
        catch {
            Write-Host "Failed to check status: $_" -ForegroundColor Red
            break
        }
    }

    if ($attempt -ge $maxAttempts) {
        Write-Host "`nMax polling attempts reached." -ForegroundColor DarkYellow
    }
}

Write-Host "========================================="
Write-Host "              Testing Done               "
Write-Host "========================================="
