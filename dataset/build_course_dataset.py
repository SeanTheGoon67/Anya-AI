#!/usr/bin/env python
"""
build_course_dataset.py — a hand-written Android + Kotlin "course".

This is teaching material in question/answer form: a student asks, a good
teacher explains in plain prose, often with a small snippet. It is what makes
Anya answer "what have you learned about coding?" with real explanations
instead of a wall of code.

    python build_course_dataset.py --out dataset\\course.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random

random.seed(3)

C = []  # (question, answer)


def q(question: str, answer: str):
    C.append((question.strip(), answer.strip()))


# --------------------------------------------------------------------------- #
# Kotlin language
# --------------------------------------------------------------------------- #
q("What is Kotlin and why is it used for Android?",
  "Kotlin is a modern, statically typed language that runs on the JVM (and can also "
  "compile to native code and JavaScript). Google made it the preferred language for "
  "Android in 2019. Compared with Java it is more concise, has built-in null safety, "
  "supports coroutines for easy async code, and adds features like data classes, "
  "extension functions and lambdas. It is fully interoperable with Java, so an Android "
  "project can mix both.")

q("What is the difference between val and var in Kotlin?",
  "`val` declares a read-only reference — you can assign it once and never reassign it, "
  "like `final` in Java. `var` is a mutable reference that can be reassigned. Prefer "
  "`val` everywhere; reach for `var` only when the value genuinely changes. Note that "
  "`val` does not make the *object* immutable, only the reference — a `val` list can "
  "still be a MutableList.")

q("How does Kotlin handle null safety?",
  "Types are non-nullable by default, so `var name: String = null` will not compile. "
  "If a value can be null you mark it with `?`: `var name: String? = null`. To use it "
  "you must handle the null case with `?.` (safe call), `?:` (Elvis operator for a "
  "default), `!!` (force-unwrap — throws if null, avoid it) or an explicit null check. "
  "This moves a common class of crashes from runtime to compile time.")

q("Explain the Kotlin Elvis operator with an example.",
  "The Elvis operator `?:` returns the left side if it is not null, otherwise the right "
  "side. It is the idiomatic way to supply a fallback:\n\n"
  "```kotlin\nval displayName = user.nickname ?: user.email ?: \"Guest\"\n```\n\n"
  "It pairs nicely with safe calls: `user?.address?.city ?: \"Unknown\"`.")

q("What are Kotlin data classes?",
  "A data class is a class whose main purpose is holding data. Writing `data class User(val id: Int, val name: String)` "
  "makes the compiler generate `equals()`, `hashCode()`, `toString()`, a `copy()` "
  "function and `componentN()` functions for destructuring. That removes a lot of "
  "boilerplate you would otherwise hand-write in Java. Data classes must have at least "
  "one constructor parameter, and only those parameters participate in the generated "
  "methods.")

q("What is a sealed class and when should I use it?",
  "A sealed class restricts which classes can inherit from it — all subclasses must be "
  "declared in the same package/module. This lets the compiler check that a `when` "
  "expression covers every case, which is perfect for modelling results:\n\n"
  "```kotlin\nsealed interface UiState {\n    object Loading : UiState\n    data class Success(val items: List<Item>) : UiState\n    data class Error(val message: String) : UiState\n}\n```\n\n"
  "Use it instead of an enum when the cases carry different data.")

q("What are Kotlin extension functions?",
  "An extension function adds a new function to a type without inheriting from it or "
  "modifying it. `fun String.shout() = uppercase() + \"!\"` lets you call "
  "`\"hi\".shout()`. Extensions are resolved statically, so they cannot override "
  "member functions or access private members. They are extremely common in Android — "
  "for example `Context.toast(\"hi\")` or `View.visible()`.")

q("Explain Kotlin scope functions: let, run, with, apply, also.",
  "They all run a block on an object, but differ in what `it`/`this` refers to and what "
  "they return.\n\n"
  "- `let` — object is `it`, returns the block result. Great for null checks: `user?.let { render(it) }`.\n"
  "- `run` — object is `this`, returns the block result. Good for a block of setup + result.\n"
  "- `with` — object is `this`, returns the block result; used when you already have the object.\n"
  "- `apply` — object is `this`, returns the object itself. Ideal for configuring a builder: `Intent().apply { action = X }`.\n"
  "- `also` — object is `it`, returns the object itself. Good for side effects like logging.\n\n"
  "Rule of thumb: `apply`/`also` when you want the same object back, `let`/`run`/`with` "
  "when you want a new value.")

q("What is a higher-order function in Kotlin?",
  "A function that takes another function as a parameter, returns one, or both. "
  "`fun repeatTwice(block: () -> Unit) { block(); block() }` is one. They are the "
  "foundation of Kotlin's collection operations — `map`, `filter`, `forEach`, `fold` — "
  "and of Compose, where UI is described by composable function calls.")

q("What is the difference between List and MutableList in Kotlin?",
  "`List` is a read-only view; you can read elements but not add or remove them. "
  "`MutableList` extends it with `add`, `remove`, `clear` and index assignment. The "
  "read-only interface is a design choice, not true immutability — the underlying "
  "object may still be mutable, but callers cannot change it through this reference.")

q("What is a lambda in Kotlin and what is the 'it' parameter?",
  "A lambda is an anonymous function written in braces: `{ x -> x * 2 }`. When a lambda "
  "takes exactly one parameter, Kotlin names it `it` automatically so you can write "
  "`list.map { it.name }`. Use `it` for short, obvious lambdas and an explicit name "
  "when it aids readability.")

q("How do I write a `when` expression in Kotlin?",
  "`when` is a switch on steroids — it matches values, ranges, types, and even arbitrary "
  "conditions:\n\n"
  "```kotlin\nval label = when (score) {\n    in 90..100 -> \"A\"\n    0 -> \"zero\"\n    else -> \"other\"\n}\n```\n\n"
  "When used as an expression it must be exhaustive. On a sealed class the compiler "
  "forces you to handle every subclass — a big safety win.")

q("What are Kotlin coroutines in simple terms?",
  "Coroutines let you write asynchronous code that reads like normal sequential code. "
  "Instead of callbacks you mark a function `suspend`, then call it from a coroutine "
  "scope. The runtime suspends the function at suspension points without blocking a "
  "thread, so you can `delay` or wait for network/database work and still keep the UI "
  "smooth. Under the hood the compiler turns each suspend function into a state "
  "machine.")

q("What is the difference between launch and async in Kotlin coroutines?",
  "Both start a coroutine inside a scope. `launch` returns a `Job` and is for "
  "fire-and-forget work whose result you do not need. `async` returns a `Deferred<T>` "
  "and is for work that produces a value; you call `.await()` to get it. Use `async` "
  "when you want to run two things in parallel and combine their results.")

q("What do Dispatchers.Main, IO and Default mean?",
  "They decide which thread pool a coroutine runs on. `Dispatchers.Main` is the Android "
  "UI thread — always switch back here before touching views or Compose state. "
  "`Dispatchers.IO` is tuned for blocking I/O like disk or network. `Dispatchers.Default` "
  "is for CPU-heavy work such as sorting or parsing. Always inject or choose the right "
  "dispatcher rather than hard-coding `Main`.")

q("What is a StateFlow and how is it different from LiveData?",
  "Both are observable data holders. `StateFlow` is a Kotlin coroutines type: it always "
  "has a current value, is hot, and you collect it in a coroutine with "
  "`collect { }` (or `collectAsStateWithLifecycle()` in Compose). `LiveData` is "
  "Android-specific, lifecycle-aware by default and observed with an `Observer`. New "
  "Compose code generally prefers `StateFlow` plus `collectAsStateWithLifecycle`.")

q("What is a suspend function?",
  "A function marked `suspend` that can pause and resume without blocking its thread. "
  "You can only call it from another suspend function or from a coroutine builder such "
  "as `launch` or `async`. Typical examples are `delay(1000)`, a Retrofit call, or a "
  "Room query. Suspension is cooperative: the coroutine gives up its thread instead of "
  "parking it, so thousands of them can run on a handful of threads.")

q("What are Kotlin generics and why use them?",
  "Generics let a class or function work with any type while keeping type safety. "
  "`fun <T> List<T>.second(): T = this[1]` returns the element type you put in. They "
  "avoid casting and prevent mistakes at compile time. Kotlin adds variance "
  "(`out`/`in`) and a reified modifier so you can inspect the type inside an inline "
  "function.")

q("What is the difference between an interface and an abstract class in Kotlin?",
  "An interface describes behaviour a class can implement — a class can implement many "
  "interfaces. An abstract class can hold state and constructors and a class can extend "
  "only one. Use an interface to model a capability (`Repository`, `ClickListener`) and "
  "an abstract class when subclasses must share real state or constructor logic.")

q("What does the companion object do in Kotlin?",
  "It holds members that belong to the class rather than to an instance — Kotlin's "
  "replacement for Java's `static`. `class Config { companion object { const val API = \"...\" } }` "
  "lets you write `Config.API`. Only one companion object is allowed per class, and it "
  "can implement an interface or be given a name.")

q("How do I use string templates in Kotlin?",
  "Put a `$` before a variable or `${...}` around an expression inside a string: "
  "`\"Hello $name, you have ${items.size} items\"`. It replaces Java-style "
  "concatenation and is much easier to read. Use `${}` whenever you need a property "
  "or a calculation.")

q("What is the safe call operator `?.` in Kotlin?",
  "`?.` calls a member only if the receiver is not null, otherwise the whole expression "
  "is null: `user?.address?.city`. Chaining safe calls lets you walk a nullable graph "
  "without nested if-checks. Combine it with `?:` to provide a default value.")

q("What are Kotlin ranges and how do I loop with them?",
  "A range is written with `..` or `until`: `1..10`, `0 until size`, or `10 downTo 1`. "
  "You can loop (`for (i in 1..10)`), test membership (`if (x in 1..10)`), and iterate "
  "with a step (`1..10 step 2`). `until` excludes the end, which is handy for indices.")

q("Explain `by lazy` in Kotlin.",
  "`by lazy { ... }` initialises a property the first time it is read and caches the "
  "result. It is thread-safe by default and is perfect for expensive objects that may "
  "never be needed, such as a database or an HTTP client: "
  "`private val api by lazy { Retrofit.Builder()...build() }`.")

q("What is the difference between `==` and `===` in Kotlin?",
  "`==` calls `equals()` and compares values (structural equality), which is what you "
  "almost always want. `===` compares references to see whether two variables point at "
  "the same object. For data classes `==` is generated for you.")

# --------------------------------------------------------------------------- #
# Android platform
# --------------------------------------------------------------------------- #
q("Explain the Android Activity lifecycle.",
  "An Activity moves through `onCreate` (set up UI, restore state) → `onStart` (now "
  "visible) → `onResume` (interactive) → `onPause` → `onStop` (no longer visible) → "
  "`onDestroy`. `onRestart` runs if the user comes back. Configure it in `onCreate` and "
  "release heavy resources in `onStop`. Rotation or a theme change can destroy and "
  "recreate the Activity, so keep UI state in a ViewModel or `SavedStateHandle` rather "
  "than in the Activity itself.")

q("What is the difference between an Activity and a Fragment?",
  "An Activity is a single, focused screen that the system can launch; a Fragment is a "
  "reusable piece of UI that lives inside an Activity or another Fragment and has its "
  "own lifecycle. Fragments let you build flexible, multi-pane layouts "
  "(list + detail on a tablet) that reuse the same code. In Compose-only apps you often "
  "skip Fragments entirely and navigate between composable destinations.")

q("What is an Intent and how do I pass data with it?",
  "An Intent is a message describing an action. An *explicit* Intent names the exact "
  "component to start (`Intent(this, DetailActivity::class.java)`); an *implicit* Intent "
  "describes an action the system resolves (`ACTION_VIEW` on a URL). Attach small "
  "values with `putExtra(\"id\", 42)` and read them with "
  "`intent.getIntExtra(\"id\", -1)`. Pass an ID and reload from the database rather "
  "than passing large objects.")

q("What is the AndroidManifest.xml for?",
  "It is the app's declaration file: it lists permissions, the application and its "
  "components (activities, services, receivers, providers), the minimum and target SDK "
  "levels, hardware features, and deep-link intent filters. The system reads it before "
  "your code runs, so anything the platform must know about your app lives there.")

q("How do runtime permissions work in Android?",
  "Dangerous permissions such as camera or location must be requested while the app is "
  "running. Declare them in the manifest, then call "
  "`registerForActivityResult(RequestPermission())` and launch it. The dialog returns "
  "whether the user granted access; always handle the denied case gracefully with a "
  "fallback or an explanation. On Android 13+ even notifications need a runtime grant.")

q("What is a ViewModel and why use one?",
  "A ViewModel holds and exposes UI state and survives configuration changes such as "
  "rotation, so the user does not lose data. It should not hold references to "
  "Activities, Fragments or Views — that leaks memory. Communicate with it through "
  "observable state (`StateFlow` or `LiveData`) and let the UI collect that state. "
  "Use `viewModelScope` for coroutines so work is cancelled when the ViewModel clears.")

q("How do I get a ViewModel in Compose?",
  "Use `viewModel()` from `androidx.lifecycle:lifecycle-viewmodel-compose`:\n\n"
  "```kotlin\nval vm: HomeViewModel = viewModel()\nval state by vm.uiState.collectAsStateWithLifecycle()\n```\n\n"
  "For simple screens that do not need a factory you can rely on the default provider; "
  "when the ViewModel needs constructor dependencies, supply a `ViewModelProvider.Factory` "
  "or let Hilt/Koin inject it.")

q("What is the difference between ViewBinding and findViewById?",
  "ViewBinding generates a type-safe class per layout, so `binding.textTitle` replaces "
  "`findViewById<TextView>(R.id.textTitle)`. It removes the risk of a wrong ID or a bad "
  "cast and is null-safe for views marked optional. Enable it in Gradle with "
  "`buildFeatures { viewBinding = true }`; DataBinding is the heavier sibling that also "
  "supports expressions in XML.")

q("How does RecyclerView work?",
  "A RecyclerView shows a long list efficiently by reusing a small pool of item views. "
  "You supply an `Adapter` that creates each row (`onCreateViewHolder`), binds data to a "
  "recycled row (`onBindViewHolder`) and reports the item count. A `LayoutManager` "
  "decides the arrangement (linear, grid, staggered). Because views are recycled, all "
  "state must be set in `onBindViewHolder` every time. In Compose, `LazyColumn` replaces "
  "it.")

q("What is Room and how do I use it?",
  "Room is a SQLite wrapper with compile-time checked queries. You annotate an `@Entity` "
  "data class for the table, a `@Dao` interface for `@Query`, `@Insert`, `@Update`, "
  "`@Delete`, and an `@Database` abstract class that ties them together. It returns "
  "`Flow` or `suspend` functions so it works naturally with coroutines, and it verifies "
  "your SQL at build time instead of crashing at runtime.")

q("What is Retrofit and how does it work with Kotlin coroutines?",
  "Retrofit turns a Kotlin interface into an HTTP client. You describe endpoints with "
  "annotations:\n\n"
  "```kotlin\ninterface Api {\n    @GET(\"users/{id}\")\n    suspend fun user(@Path(\"id\") id: Int): User\n}\n```\n\n"
  "Retrofit generates the implementation; with a `suspend` function the call runs off "
  "the main thread and returns the parsed object (via a converter such as Moshi or "
  "kotlinx.serialization). Use it inside a repository and expose the result as a Flow "
  "to the ViewModel.")

q("What is WorkManager for?",
  "WorkManager schedules deferrable, guaranteed background work that should survive app "
  "restarts — syncing data, uploading logs, periodic cleanup. You describe the task in "
  "a `Worker`, add constraints such as 'only on Wi-Fi' or 'only while charging', and "
  "enqueue it with a unique name and optional backoff. For immediate work tied to the "
  "UI use a coroutine instead; WorkManager is for work that must not be lost.")

q("How does navigation work in a modern Android app?",
  "Older apps use the Navigation component with a `nav_graph.xml` and a `NavController`. "
  "Compose apps use `androidx.navigation:navigation-compose`, declaring string routes "
  "and switching on them:\n\n"
  "```kotlin\nNavHost(nav, startDestination = \"home\") {\n    composable(\"home\") { HomeScreen(onOpen = { nav.navigate(\"detail/$it\") }) }\n    composable(\"detail/{id}\") { entry -> DetailScreen(entry.arguments?.getString(\"id\")) }\n}\n```\n\n"
  "Arguments are passed in the route and read from the back-stack entry.")

q("What is dependency injection and why use Hilt?",
  "Dependency injection means a class receives its collaborators instead of creating "
  "them itself, which makes code testable and decoupled. Hilt is Google's DI library "
  "built on Dagger: you annotate `@HiltAndroidApp` on the Application, `@Inject` "
  "constructors, and provide interfaces with `@Module`/`@Provides`. It generates all the "
  "wiring at compile time, so there is no reflection cost. Koin is a lighter, "
  "runtime-based alternative.")

q("How do I store small settings in Android?",
  "Use DataStore. `Preferences DataStore` stores key/value pairs and replaces the old "
  "`SharedPreferences`, exposing a `Flow` so changes are observable and it is safe from "
  "main-thread disk I/O. For structured objects use `Proto DataStore` with a defined "
  "schema. For user files use internal storage; for large media use external storage "
  "with scoped storage rules.")

q("What is the difference between `dp` and `sp` and `px`?",
  "`dp` is a density-independent pixel — the same physical size across screens, used "
  "for widths, heights and margins. `sp` is a scale-independent pixel that also honours "
  "the user's font-size setting, so use it for text. `px` is a raw physical pixel and is "
  "almost never used in layout code because it does not adapt to density.")

q("How do I build a simple Android screen in Jetpack Compose?",
  "A screen is a `@Composable` function. Wrap content in a layout such as `Column` or "
  "`Scaffold`, hold state with `remember { mutableStateOf(...) }`, and pass data down as "
  "parameters:\n\n"
  "```kotlin\n@Composable\nfun Counter() {\n    var count by remember { mutableStateOf(0) }\n    Column(Modifier.padding(16.dp)) {\n        Text(\"Count: $count\")\n        Button(onClick = { count++ }) { Text(\"Add\") }\n    }\n}\n```\n\n"
  "Compose re-runs the function whenever the state it reads changes.")

# --------------------------------------------------------------------------- #
# Jetpack Compose
# --------------------------------------------------------------------------- #
q("What is a @Composable function?",
  "A function annotated `@Composable` describes a piece of UI. Compose calls it to "
  "produce the UI tree, and calls it again whenever the state it reads changes. It "
  "should be a pure mapping from state to UI, take data as parameters, and emit "
  "elements like `Text`, `Column` or other composables — it should not return a view "
  "like the old View system.")

q("How does recomposition work in Compose?",
  "When state a composable reads changes, Compose schedules that composable (and only "
  "the affected parts) to run again and updates the screen. Compose keeps a record of "
  "which composables read which state. Smart recomposition means only the smallest "
  "scope that used the changed value re-executes, which is why you should keep state "
  "reads as local as possible.")

q("What is state hoisting in Compose?",
  "Moving state up out of a composable so its parent owns it, and passing the value down "
  "with a callback to change it — the 'state down, events up' pattern. A stateless "
  "`Counter(count: Int, onIncrement: () -> Unit)` is easier to test, preview and reuse "
  "than one that hides its state. Hoist to the lowest common parent that needs it.")

q("What is the difference between remember and rememberSaveable?",
  "`remember` keeps a value across recompositions but loses it when the composable "
  "leaves the composition or the process/Activity is recreated (for example on "
  "rotation). `rememberSaveable` additionally stores the value in the saved-instance "
  "state bundle so it survives rotation and process death, as long as the value can be "
  "put in a Bundle. Use `rememberSaveable` for user input you cannot afford to lose.")

q("Why is `mutableStateOf` used with `by` in Compose?",
  "`var count by remember { mutableStateOf(0) }` uses the `getValue`/`setValue` operator "
  "conventions so you can read and write `count` like an ordinary variable. Under the "
  "hood `count` is a `MutableState<Int>` whose reads are tracked by Compose, so writing "
  "to it triggers recomposition of the composables that read it.")

q("How do I show a scrolling list in Compose?",
  "Use `LazyColumn` (or `LazyRow` / `LazyVerticalGrid`). It only composes the items "
  "that are visible, so it stays fast for large data sets:\n\n"
  "```kotlin\nLazyColumn {\n    items(users, key = { it.id }) {\n        UserRow(it)\n    }\n}\n```\n\n"
  "Always give a `key` so Compose can track items correctly when the list changes.")

q("What is a Modifier in Compose?",
  "A Modifier is an ordered, immutable description of how a composable should be "
  "decorated or laid out — padding, size, background, click handling, scrolling and "
  "more. They chain: `Modifier.fillMaxWidth().padding(16.dp).clickable { }`. Order "
  "matters: `padding` before `background` leaves the background outside the padding, "
  "the reverse paints it inside.")

q("How do side effects work in Compose?",
  "`LaunchedEffect(key)` runs a suspend block when it enters the composition and "
  "restarts it when `key` changes — ideal for loading data or collecting a Flow. "
  "`DisposableEffect(key)` gives you a cleanup block for things like registering a "
  "listener. `SideEffect` runs after every successful recomposition, and "
  "`rememberCoroutineScope()` gives you a scope tied to the composable's lifetime.")

q("What is `derivedStateOf` used for?",
  "It computes a value derived from other state and only notifies readers when the "
  "*result* changes. That avoids needless recomposition — for example recomputing "
  "whether a list is scrolled to the top from a scroll position that changes on every "
  "frame. Use it sparingly; simple expressions do not need it.")

q("How do I theme a Compose app?",
  "Wrap your content in `MaterialTheme` with a `colorScheme`, `typography` and `shapes`, "
  "usually generated by Material 3. Colours are then read with `MaterialTheme.colorScheme` "
  "instead of hard-coded values, which makes dark mode and dynamic colour automatic. "
  "Material 3 also supports dynamic colour from the user's wallpaper on Android 12+.")

q("How do I write a Compose preview?",
  "Annotate a composable with `@Preview` and give it sample data, then use the Split or "
  "Design view in Android Studio. Add `showBackground = true` and a `widthDp` to see "
  "realistic framing, and create several previews for states like loading, empty and "
  "error. Previews are stripped from release builds.")

q("How do I test Compose UI?",
  "Use the Compose test rule and semantics-based finders, which mirror how a user "
  "sees the screen:\n\n"
  "```kotlin\ncomposeTestRule.setContent { App() }\ncomposeTestRule.onNodeWithText(\"Add\").performClick()\ncomposeTestRule.onNodeWithText(\"Count: 1\").assertIsDisplayed()\n```\n\n"
  "Because composables are stateless and take data as parameters, you can test them "
  "with plain input values and no emulator UI plumbing.")

q("What is a CompositionLocal?",
  "A way to pass a value implicitly down the composition tree without threading it "
  "through every composable signature — for example the current `MaterialTheme` or "
  "`LocalContext`. Provide a value with `CompositionLocalProvider(LocalFoo provides x)`. "
  "Use it for genuinely cross-cutting concerns; ordinary parameters are clearer for "
  "everything else.")

# --------------------------------------------------------------------------- #
# Architecture, quality, build
# --------------------------------------------------------------------------- #
q("What is MVVM and why is it common on Android?",
  "Model-View-ViewModel splits the app into data/model layers, a ViewModel that holds "
  "UI state and business logic, and a View (Activity, Fragment or Compose screen) that "
  "only renders state and forwards events. The ViewModel survives rotation, has no "
  "reference to the View, and is easy to unit-test, which is why it is the default "
  "recommendation in modern Android.")

q("What is a repository in Android architecture?",
  "A repository is the single place that decides where data comes from — network, "
  "database or cache — and exposes a clean API to the rest of the app (usually `Flow` "
  "or `suspend` functions). ViewModels depend on the repository interface, not on "
  "Retrofit or Room directly, so the data source can change or be faked in tests.")

q("What does unidirectional data flow mean?",
  "State flows down from a single source of truth and events flow up. The UI never "
  "mutates state directly; it sends events (like `onItemClick(id)`) to the ViewModel, "
  "which updates state, which re-renders the UI. This makes the UI a predictable "
  "function of state and removes whole classes of bugs caused by two places editing "
  "the same thing.")

q("How should I handle errors in a Kotlin Android app?",
  "Do not let exceptions escape into the UI thread. Prefer returning explicit results — "
  "a sealed `Result<T>` with `Success`/`Failure`, or `runCatching` — so the ViewModel "
  "can turn a failure into an error state the screen can render. Keep `try/catch` close "
  "to the I/O that can fail, log with a real logger, and never swallow an error "
  "silently. Avoid `!!`, which turns a null into a crash.")

q("What is the difference between a Unit test and an instrumented test?",
  "A unit test runs on the JVM with no Android device — fast, and where most of your "
  "logic tests belong (ViewModels, repositories with fakes). An instrumented test runs "
  "on a device or emulator and can touch the real Android framework, Room database or "
  "Compose UI. Put them in `src/test` and `src/androidTest` respectively.")

q("How do I make network code testable?",
  "Depend on an interface rather than a concrete client, and inject the dispatcher and "
  "the API so tests can substitute fakes and control timing. In tests use "
  "`kotlinx-coroutines-test` with `runTest` and a `StandardTestDispatcher` so "
  "`delay` is virtual and tests finish instantly. MockWebServer is useful when you want "
  "to exercise the real parsing layer.")

q("What is Gradle and what is a build.gradle.kts file?",
  "Gradle is the build system Android uses. `build.gradle.kts` declares plugins, the "
  "compile/target SDK, dependencies, build variants and build features "
  "(like Compose or ViewBinding). Settings live in `settings.gradle.kts`, shared "
  "versions are often centralised in a version catalog "
  "(`gradle/libs.versions.toml`), and the Gradle wrapper pins the version so every "
  "machine builds identically.")

q("How do I add a dependency in Kotlin DSL Gradle?",
  "Add it to the module's `build.gradle.kts`:\n\n"
  "```kotlin\ndependencies {\n    implementation(\"androidx.lifecycle:lifecycle-viewmodel-compose:2.8.0\")\n    testImplementation(\"junit:junit:4.13.2\")\n}\n```\n\n"
  "`implementation` keeps it private to the module, `api` exports it to modules that "
  "depend on you. With a version catalog you write `implementation(libs.lifecycle.viewmodel)`.")

q("What is ProGuard/R8 and when should I worry about it?",
  "R8 shrinks and obfuscates your code for release builds, removing unused classes and "
  "renaming the rest. Libraries that use reflection need keep rules in "
  "`proguard-rules.pro`, otherwise they break in release while working in debug. Always "
  "test a `release` build, not just `debug`, before shipping.")

q("How do I debug an Android app effectively?",
  "Reproduce the problem reliably first, then narrow it down: read the stack trace and "
  "the first `Caused by`, add breakpoints or log the state, and check the Android "
  "Studio Logcat filtered by your package. For UI issues inspect the layout with the "
  "Layout Inspector; for performance use the Profiler. Coroutines and recomposition "
  "problems usually show up as doing blocking work on the main thread — look for that "
  "first.")

# --------------------------------------------------------------------------- #
# Emulator front-end domain (this project's focus)
# --------------------------------------------------------------------------- #
q("What is an emulator front-end and how does it relate to Android?",
  "An emulator front-end is the app that lists your games, downloads artwork, shows "
  "system themes and then launches a separate emulator binary with the right arguments. "
  "Cocoon, Daijishou and similar apps are Android front-ends: the Android app is the UI "
  "and launcher, and the emulator (RetroArch, Dolphin and so on) does the actual "
  "emulation.")

q("What does a platform definition JSON look like in an emulator front-end?",
  "A platform record describes one console: its id, display name, the emulator package "
  "it launches, and the argument template with placeholders for the ROM path. A typical "
  "shape is\n\n"
  "```json\n{\n  \"id\": \"snes\",\n  \"name\": \"Super Nintendo\",\n  \"launch\": {\n    \"package\": \"com.retroarch\",\n    \"activity\": \"com.retroarch.browser.retroactivity.RetroActivityFuture\",\n    \"arguments\": \"-L cores/snes9x_libretro_android.so \\\"{file}\\\"\"\n  }\n}\n```\n\n"
  "The `{file}` token is replaced with the selected game's path at launch time.")

q("What is a theme.json file in a retro front-end?",
  "It is the data file that describes a custom look: colours, background images or "
  "videos, font choices, icon overlays and layout options for the home grid and detail "
  "pages. The front-end reads it to render the UI, so a theme is just structured data "
  "plus assets — you do not need to compile anything to ship a theme.")

q("How should I structure data-driven UI code so users can theme it?",
  "Keep presentation values out of the code. Load a schema-checked data object "
  "(for example `theme.json` or a platform record), map it to the UI layer, and give "
  "every field a sensible default so a missing value cannot crash the screen. Validate "
  "on load and fall back gracefully, then the same binary can look completely different "
  "depending on the data it is given.")

q("How do I launch another app from Android with arguments?",
  "Build an explicit or implicit `Intent` and pass the data as extras or as the data "
  "URI, then call `startActivity`. Many emulators accept an intent URI where the ROM "
  "path is encoded in the path and emulator flags are query parameters. Wrap the call "
  "in a `try/catch` for `ActivityNotFoundException` so a missing emulator shows a "
  "friendly message instead of crashing.")

# --------------------------------------------------------------------------- #
# Meta / self-reflection (helps her answer 'what have you learned?')
# --------------------------------------------------------------------------- #
q("What have you learned about coding?",
  "I have learned Kotlin and Jetpack Compose for Android, the Dart-free basics of "
  "building data-driven UIs, Python for scripting and tooling, and how emulator "
  "front-ends describe platforms and themes as JSON. More useful than any single "
  "language, I have learned the habits: write code that is easy to read, keep UI state "
  "in one place and flow it down, handle the null and the error case explicitly, test "
  "the logic on the JVM, and prefer small functions with clear names. Ask me for a "
  "topic and I will explain it or write the code.")

q("What is the most important thing to get right when learning to code?",
  "Learn to break a problem into small pieces and to read error messages carefully. "
  "Syntax you can look up; the things that compound are naming, keeping functions "
  "small, understanding where state lives, and testing as you go. Write code you can "
  "read again in six months.")

q("How do you approach a large codebase you have never seen?",
  "Start from the entry point and follow the data. Read the build file to see which "
  "libraries are in play, find the main screen or `main()` function, and trace one "
  "user action end to end — from the click, through the state holder, to the data "
  "layer. Once one path makes sense, the rest is variations on it. I resist rewriting "
  "until I understand why the current shape exists.")

q("Who are you?",
  "I am Anya, a small local coding assistant running entirely offline on this PC "
  "through Ollama. I know the formats used by retro emulator front-ends — platform "
  "JSON and theme.json — as well as Kotlin, Jetpack Compose and Python, and I am happy "
  "to just chat as well as write code.")

q("What can you help me with?",
  "Two things, mostly. We can chat — ask me anything, brainstorm, or explain something "
  "and I will answer in plain language. And I can write and review code: Python, Kotlin "
  "and Jetpack Compose for Android, plus emulator front-end config such as platforms "
  "and theme.json files. If you want raw code only, just say 'code only'.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=r"dataset\course.jsonl")
    args = ap.parse_args()

    rows, seen = [], set()
    for question, answer in C:
        key = question.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"instruction": question, "input": "", "output": answer})

    random.shuffle(rows)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] {len(rows)} course Q&A examples -> {args.out}")


if __name__ == "__main__":
    main()
