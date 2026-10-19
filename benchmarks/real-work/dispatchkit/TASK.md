Three bugs are open against dispatchkit. Invoices and receipts that share an event id are being treated as the same delivery, so one of them is dropped as a duplicate. A 429 from the provider stops the retry loop after the first attempt. And the first retry waits twice as long as the README says it should.

Plan this as four todos, then do them in order: read the tests and the dispatch package, fix the dedupe key, fix the retry delay, and make the worker retry a rate limit. Then run python -m pytest and make all tests pass. Do not edit the tests.
