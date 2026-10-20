
stage('Validate Trigger') {
    when {
        expression {
            return params.IMAGE_TAG?.trim()
        }
    }

    steps {
        script {
            // 1. Read deployment parameters
            def branch = params.SOURCE_BRANCH?.trim() ?: ''
            def commit = params.GIT_COMMIT?.trim() ?: ''
            def target = params.DEPLOY_TARGET?.trim()?.toLowerCase() ?: ''

            // 2. Validate mandatory parameters
            if (!branch || !commit) {
                error(
                    "SOURCE_BRANCH and GIT_COMMIT are mandatory for deployment"
                )
            }

            if (!(commit ==~ /(?i)[0-9a-f]{40}/)) {
                error(
                    "GIT_COMMIT must be a complete 40-character SHA"
                )
            }

            if (!(target in ['nmdb', 'nec'])) {
                error(
                    "Invalid DEPLOY_TARGET: ${target}. Expected nmdb or nec"
                )
            }

            // 3. Identify source branch type
            def normalizedBranch = branch.toLowerCase()
            def isMain = normalizedBranch == 'main'

            // Explicit NEC branch naming
            def isNec = normalizedBranch == 'nec' ||
                        normalizedBranch.startsWith('nec/') ||
                        normalizedBranch.endsWith('-nec') ||
                        normalizedBranch.contains('/nec-')

            // 4. Determine expected deployment target
            def expectedTarget = isNec ? 'nec' : 'nmdb'

            // 5. Validate branch and target
            if (!isMain && target != expectedTarget) {
                error(
                    "Deployment target mismatch. " +
                    "Branch '${branch}' requires '${expectedTarget}', " +
                    "but received '${target}'."
                )
            }

            // 6. Log validation details
            echo "======================================"
            echo "DEPLOYMENT VALIDATION"
            echo "======================================"
            echo "Source Branch  : ${branch}"
            echo "Git Commit     : ${commit}"
            echo "Image Tag      : ${params.IMAGE_TAG}"
            echo "Deploy Target  : ${target}"
            echo "Main Branch    : ${isMain}"
            echo "NEC Branch     : ${isNec}"
            echo "Expected Target: ${isMain ? 'nmdb / nec' : expectedTarget}"
            echo "======================================"
            echo "Deployment validation successful"
        }
    }
}
